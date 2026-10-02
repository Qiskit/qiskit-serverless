"""Unit tests for OutboxTask."""

from unittest.mock import MagicMock, patch

import pytest

from core.config_key import ConfigKey
from core.models import Config, Job, Outbox, OutboxChannel, Program
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from core.ibm_cloud.event_streams.kafka_sender import KafkaSender
from core.ibm_cloud.sender import PendingMessage
from scheduler.tasks.outbox import _build_kafka_breaker, BreakerRegistry, OutboxTask

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.outbox"


def _sender(delivers=lambda pk: True) -> MagicMock:
    """A sender whose send_batch confirms the rows `delivers(pk)` accepts."""
    sender = MagicMock()
    sender.send_batch.side_effect = lambda messages: {m.key for m in messages if delivers(m.key)}
    return sender


def _make_task(sender=None) -> OutboxTask:
    # Config.get_int's `default=` only covers a non-numeric value, never a missing row: a key
    # with no seeded row raises KeyError. add_defaults() seeds budget_ms/breaker_failures/
    # breaker_pause_seconds from settings.DYNAMIC_CONFIG_DEFAULTS so every test can call
    # task.run() without fixing each of those three keys by hand.
    Config.add_defaults()
    task = OutboxTask(KillSignal(), MagicMock(spec=SchedulerMetrics))
    if sender is not None:
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_channel(sender)}
    return task


def _kafka_channel(sender, breakers=None) -> OutboxTask.Channel:
    return OutboxTask.Channel(
        sender=sender,
        breakers=breakers or BreakerRegistry(_build_kafka_breaker),
        budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS,
    )


def _make_job() -> Job:
    from django.contrib.auth.models import User

    user, _ = User.objects.get_or_create(username="author")
    return Job.objects.create(author=user, runner=Program.FLEETS)


def _make_row(job=None, payload=None, region=None) -> Outbox:
    return Outbox.objects.create(
        job=job or _make_job(), channel=OutboxChannel.JOB_USAGE, region=region, payload=payload or {"data": {}}
    )


class TestHappyPath:
    def test_sends_and_deletes_the_row_on_success(self):
        sender = _sender()
        task = _make_task(sender=sender)
        row = _make_row(payload={"data": {"metric_type": "license_ibm-dev_fn_m"}})

        task.run()

        sender.send_batch.assert_called_once_with([PendingMessage(row.pk, row.payload)])
        assert not Outbox.objects.filter(pk=row.pk).exists()

    def test_sends_every_pending_row_in_one_batch(self):
        sender = _sender()
        task = _make_task(sender=sender)
        _make_row()
        _make_row()

        task.run()

        sender.send_batch.assert_called_once()
        assert len(sender.send_batch.call_args.args[0]) == 2
        assert Outbox.objects.count() == 0


class TestFailureHandling:
    def test_a_failed_batch_leaves_the_rows_and_opens_the_breaker(self):
        task = _make_task(sender=_sender(delivers=lambda pk: False))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        row = _make_row()

        task.run()

        assert Outbox.objects.filter(pk=row.pk).exists()
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is True

    def test_only_the_confirmed_rows_are_deleted_and_the_breaker_stays_closed(self):
        bad_row = _make_row()
        good_row = _make_row()
        task = _make_task(sender=_sender(delivers=lambda pk: pk != bad_row.pk))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")

        task.run()

        assert Outbox.objects.filter(pk=bad_row.pk).exists()
        assert not Outbox.objects.filter(pk=good_row.pk).exists()
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is False


class TestBreakerIsolationBetweenChannels:
    def test_one_channel_failing_does_not_stop_another_from_draining_the_same_tick(self):
        billing_sender = _sender(delivers=lambda pk: False)
        workload_sender = _sender()
        task = _make_task()
        task.channels = {
            OutboxChannel.JOB_USAGE: _kafka_channel(billing_sender),
            "workload": _kafka_channel(workload_sender),
        }
        billing_row = _make_row()  # channel=OutboxChannel.USAGE, will fail
        workload_row = Outbox.objects.create(job=_make_job(), channel="workload", payload={})

        task.run()

        assert Outbox.objects.filter(pk=billing_row.pk).exists()  # failed, kept for retry
        assert not Outbox.objects.filter(pk=workload_row.pk).exists()  # succeeded, deleted

    def test_an_open_breaker_on_one_channel_does_not_skip_another_channel(self):
        billing_sender = _sender(delivers=lambda pk: False)
        workload_sender = _sender()
        task = _make_task()
        task.channels = {
            OutboxChannel.JOB_USAGE: _kafka_channel(billing_sender),
            "workload": _kafka_channel(workload_sender),
        }
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        _make_row()  # trips the usage breaker on this first run()
        task.run()
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is True

        workload_row = Outbox.objects.create(job=_make_job(), channel="workload", payload={})
        task.run()  # billing breaker open and skipped; workload must still be attempted

        workload_sender.send_batch.assert_called_once()
        assert not Outbox.objects.filter(pk=workload_row.pk).exists()


class TestSharedBreakerAcrossChannelsWithTheSameSender:
    def test_a_failure_on_one_channel_opens_the_breaker_for_the_other(self):
        """LICENSE_FEE and USAGE share one sender in production, so a failure on either must
        open the same breaker for both, instead of each counting its own failures."""
        shared_sender = _sender(delivers=lambda pk: False)
        shared_breakers = BreakerRegistry(_build_kafka_breaker)
        task = _make_task()
        task.channels = {
            OutboxChannel.LICENSE_FEE: _kafka_channel(shared_sender, shared_breakers),
            OutboxChannel.JOB_USAGE: _kafka_channel(shared_sender, shared_breakers),
        }
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        Outbox.objects.create(job=_make_job(), channel=OutboxChannel.LICENSE_FEE, payload={"data": {}})
        billing_row = Outbox.objects.create(job=_make_job(), channel=OutboxChannel.JOB_USAGE, payload={"data": {}})

        task.run()

        assert task.channels[OutboxChannel.LICENSE_FEE].breakers.get(None).is_open is True
        assert shared_sender.send_batch.call_count == 1  # USAGE skipped: breaker already open
        assert Outbox.objects.filter(pk=billing_row.pk).exists()


class TestBudgetAndKillSignal:
    def test_stops_once_the_time_budget_is_spent(self):
        sender = _sender()
        task = _make_task(sender=sender)
        _make_row()
        _make_row()
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS, "0")

        with patch(f"{_MOD}.time.monotonic", side_effect=[0.0, 100.0]):
            task.run()

        sender.send_batch.assert_not_called()

    def test_stops_when_kill_signal_received(self):
        sender = _sender()
        task = _make_task(sender=sender)
        task.kill_signal.received = True
        _make_row()

        task.run()

        sender.send_batch.assert_not_called()


class TestMultipleBatches:
    def test_keeps_fetching_until_nothing_pending(self):
        sender = _sender()
        task = _make_task(sender=sender)
        with patch(f"{_MOD}.BATCH_SIZE", 1):
            _make_row()
            _make_row()
            task.run()

        assert sender.send_batch.call_count == 2


class TestPartialSuccessWithARealKafkaSender:
    class _Producer:
        def __init__(self, reject, hang=()):
            self.reject, self.hang, self.queued = reject, hang, []

        def produce(self, **kwargs):
            self.queued.append(kwargs)

        def flush(self, timeout):
            outstanding = 0
            for kwargs in self.queued:
                if kwargs["key"] in self.hang:
                    outstanding += 1
                    continue
                error = Exception("rejected") if kwargs["key"] in self.reject else None
                kwargs["callback"](error, None)
            self.queued = []
            return outstanding

    @staticmethod
    def _task_with_kafka(reject_subjects, hang_subjects=()):
        producers = MagicMock()
        producers.topic = "t"
        producers.get.return_value = TestPartialSuccessWithARealKafkaSender._Producer(reject_subjects, hang_subjects)
        task = _make_task()
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_channel(KafkaSender(producers))}
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        return task

    @staticmethod
    def _row(subject):
        return _make_row(payload={"subject": subject, "data": {}})

    def test_one_rejected_row_is_kept_and_does_not_open_the_breaker(self):
        task = self._task_with_kafka({b"bad"})
        bad, good = self._row("bad"), self._row("good")

        task.run()

        assert Outbox.objects.filter(pk=bad.pk).exists()
        assert not Outbox.objects.filter(pk=good.pk).exists()
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is False

    def test_a_batch_where_every_row_is_rejected_opens_the_breaker(self):
        task = self._task_with_kafka({b"bad-1", b"bad-2"})
        first, second = self._row("bad-1"), self._row("bad-2")

        task.run()

        assert Outbox.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is True

    def test_rows_still_outstanding_after_the_flush_are_kept_and_count_as_a_failed_batch(self):
        task = self._task_with_kafka(set(), hang_subjects={b"slow-1", b"slow-2"})
        first, second = self._row("slow-1"), self._row("slow-2")

        task.run()

        assert Outbox.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
        assert task.channels[OutboxChannel.JOB_USAGE].breakers.get(None).is_open is True

    def test_a_payload_that_is_not_even_a_dict_does_not_stop_the_other_rows(self):
        task = self._task_with_kafka(set())
        broken = _make_row(payload=[1, 2, 3])
        good = self._row("good")

        task.run()  # must not raise

        assert Outbox.objects.filter(pk=broken.pk).exists()
        assert not Outbox.objects.filter(pk=good.pk).exists()


class TestRegionsAreIndependent:
    @staticmethod
    def _row_in(region):
        return _make_row(payload={"region": region, "data": {}}, region=region)

    @staticmethod
    def _regional_sender(dead_region):
        sender = _sender()
        sender.send_batch.side_effect = lambda messages: {m.key for m in messages if m.payload["region"] != dead_region}
        return sender

    def test_each_region_is_sent_in_its_own_batch(self):
        sender = self._regional_sender(dead_region=None)
        task = _make_task(sender=sender)
        east, west = self._row_in("us-east"), self._row_in("eu-de")

        task.run()

        sent = [[m.key for m in call.args[0]] for call in sender.send_batch.call_args_list]
        assert sorted(sent) == sorted([[east.pk], [west.pk]])
        assert Outbox.objects.count() == 0

    def test_a_dead_region_opens_only_its_own_breaker_and_the_healthy_region_keeps_draining(self):
        sender = self._regional_sender(dead_region="eu-de")
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        dead = self._row_in("eu-de")
        self._row_in("us-east")

        task.run()

        breakers = task.channels[OutboxChannel.JOB_USAGE].breakers
        assert breakers.get("eu-de").is_open is True
        assert breakers.get("us-east").is_open is False
        assert list(Outbox.objects.values_list("pk", flat=True)) == [dead.pk]

    def test_a_region_with_an_open_breaker_is_skipped_while_the_others_are_still_sent(self):
        sender = self._regional_sender(dead_region="eu-de")
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        self._row_in("eu-de")
        task.run()  # opens the eu-de breaker
        sender.send_batch.reset_mock()
        dead, healthy = self._row_in("eu-de"), self._row_in("us-east")

        task.run()

        sent_keys = [m.key for call in sender.send_batch.call_args_list for m in call.args[0]]
        assert sent_keys == [healthy.pk]  # the eu-de rows were not even attempted
        assert Outbox.objects.filter(pk=dead.pk).exists()
        assert not Outbox.objects.filter(pk=healthy.pk).exists()


class TestOpenBreakersAndTheScan:
    @staticmethod
    def _regional_sender(dead_region):
        sender = _sender()
        sender.send_batch.side_effect = lambda messages: {m.key for m in messages if m.payload["region"] != dead_region}
        return sender

    @staticmethod
    def _row_in(region):
        return _make_row(payload={"region": region, "data": {}}, region=region)

    def test_when_every_breaker_is_open_nothing_is_sent_and_the_tick_ends(self):
        sender = self._regional_sender(dead_region="eu-de")
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        self._row_in("eu-de")
        task.run()  # opens the eu-de breaker
        sender.send_batch.reset_mock()
        for _ in range(3):
            self._row_in("eu-de")

        with patch(f"{_MOD}.BATCH_SIZE", 1):
            task.run()

        sender.send_batch.assert_not_called()
        assert Outbox.objects.count() == 4

    def test_healthy_rows_behind_a_pile_of_dead_ones_are_still_reached(self):
        sender = self._regional_sender(dead_region="eu-de")
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        self._row_in("eu-de")
        task.run()  # opens the eu-de breaker
        sender.send_batch.reset_mock()
        for _ in range(3):
            self._row_in("eu-de")
        healthy = self._row_in("us-east")

        with patch(f"{_MOD}.BATCH_SIZE", 1):  # the dead rows fill several batches before the healthy one
            task.run()

        assert not Outbox.objects.filter(pk=healthy.pk).exists()
        sent_keys = [m.key for call in sender.send_batch.call_args_list for m in call.args[0]]
        assert sent_keys == [healthy.pk]


class TestBreakerGauge:
    def test_the_gauge_reflects_the_breaker_that_this_tick_just_opened(self):
        task = _make_task(sender=_sender(delivers=lambda pk: False))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        _make_row()

        task.run()

        task.metrics.set_outbox_breaker_open.assert_called_with(True, channel=OutboxChannel.JOB_USAGE)
