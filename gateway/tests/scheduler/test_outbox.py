"""Unit tests for OutboxTask."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.clients.workload_sender import WorkloadSender
from core.config_key import ConfigKey
from core.models import Config, Job, Outbox, OutboxChannel, Program
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from core.ibm_cloud.event_streams.kafka_sender import KafkaSender
from core.ibm_cloud.sender import BatchSender, PendingMessage, Sender
from scheduler.tasks.outbox import OutboxTask, build_kafka_circuit_breaker, build_workload_circuit_breaker
from scheduler.tasks.outbox_destination import Destination

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.outbox_destination"


def _sender(delivers=lambda pk: True) -> MagicMock:
    """A sender whose send_batch confirms the rows `delivers(pk)` accepts."""
    sender = MagicMock(spec=BatchSender)
    sender.send_batch.side_effect = lambda messages: {m.key for m in messages if delivers(m.key)}
    return sender


def _single_sender(fails=lambda payload: False) -> MagicMock:
    """A sender with no batch support, whose send raises for the payloads `fails(payload)` accepts."""
    sender = MagicMock(spec=Sender)

    def send(payload):
        if fails(payload):
            raise RuntimeError("boom")

    sender.send.side_effect = send
    return sender


def _make_task(sender=None) -> OutboxTask:
    # Config.get_int's `default=` only covers a non-numeric value, never a missing row: a key
    # with no seeded row raises KeyError. add_defaults() seeds budget_ms/breaker_failures/
    # breaker_pause_seconds from settings.DYNAMIC_CONFIG_DEFAULTS so every test can call
    # task.run() without fixing each of those three keys by hand.
    Config.add_defaults()
    task = OutboxTask(KillSignal(), MagicMock(spec=SchedulerMetrics))
    if sender is not None:
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_destination(task, sender)}
    return task


def _kafka_destination(task, sender) -> Destination:
    return Destination(
        metrics=task.metrics,
        kill_signal=task.kill_signal,
        sender=sender,
        breaker_factory=build_kafka_circuit_breaker,
        budget_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS,
        retry_base_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_BASE_SECONDS,
        retry_max_key=ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_MAX_SECONDS,
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
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True

    def test_only_the_confirmed_rows_are_deleted_and_the_breaker_stays_closed(self):
        bad_row = _make_row()
        good_row = _make_row()
        task = _make_task(sender=_sender(delivers=lambda pk: pk != bad_row.pk))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")

        task.run()

        assert Outbox.objects.filter(pk=bad_row.pk).exists()
        assert not Outbox.objects.filter(pk=good_row.pk).exists()
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is False


class TestBreakerIsolationBetweenChannels:
    def test_one_channel_failing_does_not_stop_another_from_draining_the_same_tick(self):
        billing_sender = _sender(delivers=lambda pk: False)
        other_sender = _sender()
        task = _make_task()
        task.channels = {
            OutboxChannel.JOB_USAGE: _kafka_destination(task, billing_sender),
            "other": _kafka_destination(task, other_sender),
        }
        billing_row = _make_row()  # channel=OutboxChannel.USAGE, will fail
        other_row = Outbox.objects.create(job=_make_job(), channel="other", payload={})

        task.run()

        assert Outbox.objects.filter(pk=billing_row.pk).exists()  # failed, kept for retry
        assert not Outbox.objects.filter(pk=other_row.pk).exists()  # succeeded, deleted

    def test_an_open_breaker_on_one_channel_does_not_skip_another_channel(self):
        billing_sender = _sender(delivers=lambda pk: False)
        other_sender = _sender()
        task = _make_task()
        task.channels = {
            OutboxChannel.JOB_USAGE: _kafka_destination(task, billing_sender),
            "other": _kafka_destination(task, other_sender),
        }
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        _make_row()  # trips the usage breaker on this first run()
        task.run()
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True

        other_row = Outbox.objects.create(job=_make_job(), channel="other", payload={})
        task.run()  # billing breaker open and skipped; workload must still be attempted

        other_sender.send_batch.assert_called_once()
        assert not Outbox.objects.filter(pk=other_row.pk).exists()


class TestSharedBreakerAcrossChannelsWithTheSameDestination:
    def test_a_failure_on_one_channel_opens_the_breaker_for_the_other(self):
        """LICENSE_FEE and USAGE share one destination in production, so a failure on either must
        open the same breaker for both, instead of each counting its own failures."""
        shared_sender = _sender(delivers=lambda pk: False)
        task = _make_task()
        shared = _kafka_destination(task, shared_sender)
        task.channels = {OutboxChannel.LICENSE_FEE: shared, OutboxChannel.JOB_USAGE: shared}
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        Outbox.objects.create(job=_make_job(), channel=OutboxChannel.LICENSE_FEE, payload={"data": {}})
        billing_row = Outbox.objects.create(job=_make_job(), channel=OutboxChannel.JOB_USAGE, payload={"data": {}})

        task.run()

        assert task.channels[OutboxChannel.LICENSE_FEE].get_breaker(None).is_open is True
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

    def test_the_drain_itself_stops_when_the_kill_signal_arrives(self):
        sender = _sender()
        task = _make_task(sender=sender)
        task.kill_signal.received = True
        _make_row()

        task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)  # not through run()

        sender.send_batch.assert_not_called()

    def test_stops_when_kill_signal_received(self):
        sender = _sender()
        task = _make_task(sender=sender)
        task.kill_signal.received = True
        _make_row()

        with patch.object(Destination, "drain") as drain:
            task.run()

        drain.assert_not_called()  # the channel loop itself stopped
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
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_destination(task, KafkaSender(producers))}
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
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is False

    def test_a_batch_where_every_row_is_rejected_opens_the_breaker(self):
        task = self._task_with_kafka({b"bad-1", b"bad-2"})
        first, second = self._row("bad-1"), self._row("bad-2")

        task.run()

        assert Outbox.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True

    def test_rows_still_outstanding_after_the_flush_are_kept_and_count_as_a_failed_batch(self):
        task = self._task_with_kafka(set(), hang_subjects={b"slow-1", b"slow-2"})
        first, second = self._row("slow-1"), self._row("slow-2")

        task.run()

        assert Outbox.objects.filter(pk__in=[first.pk, second.pk]).count() == 2
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True

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

        destination = task.channels[OutboxChannel.JOB_USAGE]
        assert destination.get_breaker("eu-de").is_open is True
        assert destination.get_breaker("us-east").is_open is False
        assert list(Outbox.objects.values_list("pk", flat=True)) == [dead.pk]

    def test_rows_without_a_region_are_drained_apart_from_the_regional_ones(self):
        sender = self._regional_sender(dead_region="no-such-region")
        task = _make_task(sender=sender)
        regional, unregional = self._row_in("eu-de"), self._row_in(None)

        task.run()

        sent = [[m.key for m in call.args[0]] for call in sender.send_batch.call_args_list]
        assert sorted(sent) == sorted([[regional.pk], [unregional.pk]])
        assert Outbox.objects.count() == 0

    def test_a_breaker_that_opens_mid_region_keeps_the_rest_of_that_region_from_being_sent(self):
        sender = self._regional_sender(dead_region="eu-de")
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        self._row_in("eu-de")
        self._row_in("eu-de")

        with patch(f"{_MOD}.BATCH_SIZE", 1):
            task.run()

        assert sender.send_batch.call_count == 1  # the second eu-de batch was never attempted

    def test_the_region_with_the_oldest_row_is_sent_first(self):
        sender = self._regional_sender(dead_region="no-such-region")
        task = _make_task(sender=sender)
        oldest, newest = self._row_in("eu-de"), self._row_in("us-east")

        task.run()

        sent = [[m.key for m in call.args[0]] for call in sender.send_batch.call_args_list]
        assert sent == [[oldest.pk], [newest.pk]]

    def test_a_region_with_an_open_breaker_is_not_even_read(self):
        task = _make_task(sender=self._regional_sender(dead_region="eu-de"))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        self._row_in("eu-de")
        task.run()  # opens the eu-de breaker
        self._row_in("eu-de")

        with CaptureQueriesContext(connection) as queries:
            task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)

        # the list of pending regions is the only thing read: no query asks for the rows of a region
        assert not any('"region" = ' in query["sql"] for query in queries)

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

    def test_channels_sharing_a_destination_report_the_same_state_even_if_a_later_one_opened_it(self):
        task = _make_task()
        shared = _kafka_destination(task, _sender(delivers=lambda pk: False))
        task.channels = {OutboxChannel.LICENSE_FEE: shared, OutboxChannel.JOB_USAGE: shared}
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1")
        _make_row()  # only the second channel has rows, so it is the one that opens the shared breaker

        task.run()

        task.metrics.set_outbox_breaker_open.assert_any_call(True, channel=OutboxChannel.LICENSE_FEE)
        task.metrics.set_outbox_breaker_open.assert_any_call(True, channel=OutboxChannel.JOB_USAGE)


class TestSendersWithoutBatches:
    """A sender with only send() gets its rows one by one, and every failure counts for the breaker at once."""

    def test_each_row_is_sent_on_its_own_and_deleted_when_delivered(self):
        sender = _single_sender()
        task = _make_task(sender=sender)
        rows = [_make_row() for _ in range(3)]

        task.run()

        assert sender.send.call_count == 3
        assert Outbox.objects.count() == 0
        assert task.metrics.increment_outbox_send.call_args_list == [((row.channel, "success"),) for row in rows]

    def test_the_failure_that_opens_the_breaker_stops_the_rest_of_the_region(self):
        sender = _single_sender(fails=lambda payload: True)
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "2")
        for _ in range(5):
            _make_row()

        task.run()

        assert sender.send.call_count == 2  # the third row was never attempted
        assert Outbox.objects.count() == 5  # nothing is deleted when it fails
        assert task.metrics.increment_outbox_send.call_args_list == [((OutboxChannel.JOB_USAGE, "failure"),)] * 2
        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True

    def test_a_success_between_failures_keeps_the_breaker_closed(self):
        sender = _single_sender(fails=lambda payload: payload.get("bad", False))
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "2")
        bad_one = _make_row(payload={"bad": True, "data": {}})
        _make_row()
        bad_two = _make_row(payload={"bad": True, "data": {}})

        task.run()

        assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is False
        assert sorted(Outbox.objects.values_list("pk", flat=True)) == sorted([bad_one.pk, bad_two.pk])

    def test_the_kill_signal_stops_the_rest_of_the_batch(self):
        task = _make_task()
        sender = _single_sender()
        sender.send.side_effect = lambda payload: setattr(task.kill_signal, "received", True)
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_destination(task, sender)}
        for _ in range(3):
            _make_row()

        task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)

        assert sender.send.call_count == 1  # the kill signal arrived during the first send
        assert Outbox.objects.count() == 2  # the delivered row is gone, the others wait for the next tick

    def test_a_spent_time_budget_stops_the_rest_of_the_batch(self):
        task = _make_task()
        clock = [0.0]
        sender = _single_sender()
        sender.send.side_effect = lambda payload: clock.__setitem__(0, 100.0)  # a slow send spends the budget
        task.channels = {OutboxChannel.JOB_USAGE: _kafka_destination(task, sender)}
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BUDGET_MS, "1000")
        for _ in range(3):
            _make_row()

        with patch(f"{_MOD}.time.monotonic", side_effect=lambda: clock[0]):
            task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)

        assert sender.send.call_count == 1
        assert Outbox.objects.count() == 2


class TestRetryWithBackoff:
    """A row that fails is kept with its attempt recorded and left alone until its wait is over, so a row that
    always fails cannot keep the rows behind it from being sent."""

    @staticmethod
    def _wait_of(row) -> timedelta:
        return row.next_attempt_at - timezone.now()

    def test_a_failed_row_records_the_attempt_and_waits(self):
        row = _make_row()
        task = _make_task(sender=_single_sender(fails=lambda payload: True))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "100")

        task.run()

        row.refresh_from_db()
        assert row.attempts == 1
        assert row.last_error == "RuntimeError: boom"
        assert self._wait_of(row) > timedelta(seconds=60)  # the default base is two minutes

    def test_the_rows_a_batch_sender_did_not_confirm_record_the_attempt_too(self):
        bad_row = _make_row()
        good_row = _make_row()
        task = _make_task(sender=_sender(delivers=lambda pk: pk != bad_row.pk))

        task.run()

        bad_row.refresh_from_db()
        assert bad_row.attempts == 1
        assert bad_row.last_error == "not confirmed by the sender"
        assert self._wait_of(bad_row) > timedelta(seconds=60)
        assert not Outbox.objects.filter(pk=good_row.pk).exists()

    def test_a_batch_where_nothing_was_confirmed_makes_every_row_wait(self):
        sender = _sender(delivers=lambda pk: False)
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "100")
        row = _make_row()
        task.run()

        row.refresh_from_db()
        assert (row.attempts, self._wait_of(row) > timedelta(seconds=60)) == (1, True)
        sender.send_batch.reset_mock()
        task.run()
        sender.send_batch.assert_not_called()

    def test_a_row_that_is_still_waiting_is_not_sent_again(self):
        sender = _single_sender(fails=lambda payload: True)
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1000000")  # the breaker must not be what stops it
        _make_row()
        task.run()
        sender.send.reset_mock()

        task.run()

        sender.send.assert_not_called()

    def test_a_row_is_sent_again_and_deleted_once_its_wait_is_over(self):
        sender = _single_sender()
        task = _make_task(sender=sender)
        row = _make_row()
        Outbox.objects.filter(pk=row.pk).update(attempts=2, next_attempt_at=timezone.now() - timedelta(seconds=1))

        task.run()

        sender.send.assert_called_once()
        assert not Outbox.objects.filter(pk=row.pk).exists()

    def test_the_attempts_keep_growing_across_ticks(self):
        task = _make_task(sender=_single_sender(fails=lambda payload: True))
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "1000000")
        row = _make_row()
        for expected in (1, 2):
            task.run()
            Outbox.objects.filter(pk=row.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
            row.refresh_from_db()
            assert row.attempts == expected

    def test_the_wait_doubles_with_every_attempt_and_stops_at_the_cap(self):
        Config.add_defaults()
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_BASE_SECONDS, "30")
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_MAX_SECONDS, "100")
        waits = []
        for attempts_so_far in (0, 1, 2, 3, 2_000_000_000):
            row = _make_row()
            Outbox.objects.filter(pk=row.pk).update(attempts=attempts_so_far)
            task = _make_task(sender=_single_sender(fails=lambda payload: True))
            Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "100")
            now = timezone.now()
            with patch(f"{_MOD}.timezone.now", return_value=now):
                task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)
            row.refresh_from_db()
            waits.append(row.next_attempt_at - now)
            row.delete()

        assert waits == [timedelta(seconds=s) for s in (30, 60, 100, 100, 100)]

    def test_the_defaults_wait_two_minutes_and_stop_at_ten(self):
        Config.add_defaults()
        waits = []
        for attempts_so_far in (0, 10):
            row = _make_row()
            Outbox.objects.filter(pk=row.pk).update(attempts=attempts_so_far)
            task = _make_task(sender=_single_sender(fails=lambda payload: True))
            now = timezone.now()
            with patch(f"{_MOD}.timezone.now", return_value=now):
                task.channels[OutboxChannel.JOB_USAGE].drain(OutboxChannel.JOB_USAGE)
            row.refresh_from_db()
            waits.append(row.next_attempt_at - now)
            row.delete()

        assert waits == [timedelta(seconds=120), timedelta(seconds=600)]

    def test_the_wait_is_at_least_one_second_even_if_the_base_is_zero(self):
        sender = _single_sender(fails=lambda payload: True)
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "100")
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_RETRY_BASE_SECONDS, "0")
        row = _make_row()

        task.run()

        row.refresh_from_db()
        assert sender.send.call_count == 1  # not retried in a loop for the rest of the tick
        assert self._wait_of(row) > timedelta(milliseconds=500)

    def test_an_error_message_longer_than_the_column_or_with_a_nul_is_stored_cut_and_clean(self):
        sender = _single_sender()
        sender.send.side_effect = RuntimeError("x" * 2000 + "\x00")
        task = _make_task(sender=sender)
        row = _make_row()

        task.run()

        row.refresh_from_db()
        assert len(row.last_error) == 500
        assert row.last_error.startswith("RuntimeError: xxx")
        assert "\x00" not in row.last_error

    def test_a_region_with_only_waiting_rows_is_not_even_visited(self):
        sender = _single_sender()
        task = _make_task(sender=sender)
        waiting = _make_row(region="eu-de")
        Outbox.objects.filter(pk=waiting.pk).update(attempts=1, next_attempt_at=timezone.now() + timedelta(hours=1))
        _make_row(region="us-east")

        task.run()

        assert set(task.channels[OutboxChannel.JOB_USAGE].breakers) == {"us-east"}

    def test_rows_that_never_failed_go_before_the_ones_that_did(self):
        sent = []
        sender = _single_sender()
        sender.send.side_effect = lambda payload: sent.append(payload["name"])
        task = _make_task(sender=sender)
        old_failed = [_make_row(payload={"name": f"failed-{i}", "data": {}}) for i in range(3)]
        fresh = _make_row(payload={"name": "fresh", "data": {}})
        Outbox.objects.filter(pk__in=[r.pk for r in old_failed]).update(attempts=1)

        task.run()

        assert sent[0] == "fresh"
        assert not Outbox.objects.filter(pk=fresh.pk).exists()

    def test_a_group_of_rows_that_always_fail_does_not_block_the_rows_behind_them_once_the_breaker_reopens(self):
        """The breaker opens and its pause passes. The failing rows are waiting, so what is sent next is the fresh
        row instead of the oldest bad ones, and its success is what keeps the breaker closed."""
        clock = [0.0]  # seconds since the start, for both the monotonic clock (the breaker) and the wall clock
        sender = _single_sender(fails=lambda payload: payload.get("bad", False))
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_FAILURES, "3")
        Config.set(ConfigKey.OUTBOX_KAFKA_CHANNEL_BREAKER_PAUSE_SECONDS, "60")
        bad_rows = [_make_row(payload={"bad": True, "data": {}}) for _ in range(3)]
        good_row = _make_row()
        base = timezone.now()  # after the rows exist, so all of them are due at clock 0

        with (
            patch("time.monotonic", side_effect=lambda: clock[0]),
            patch("django.utils.timezone.now", side_effect=lambda: base + timedelta(seconds=clock[0])),
        ):
            task.run()  # the three bad rows fail and open the breaker
            assert task.channels[OutboxChannel.JOB_USAGE].get_breaker(None).is_open is True
            clock[0] = 70.0  # past the breaker's pause (60 s) and still inside the wait of the bad rows (120 s)
            task.run()

        assert not Outbox.objects.filter(pk=good_row.pk).exists()
        assert Outbox.objects.filter(pk__in=[r.pk for r in bad_rows]).count() == 3


class TestWorkloadChannel:
    """The workload channel is registered by default."""

    def _task_with_workload_sender(self, sender):
        task = _make_task()
        assert isinstance(task.channels[OutboxChannel.WORKLOAD].sender, WorkloadSender)
        task.channels = {
            OutboxChannel.WORKLOAD: Destination(
                metrics=task.metrics,
                kill_signal=task.kill_signal,
                sender=sender,
                breaker_factory=build_workload_circuit_breaker,
                budget_key=ConfigKey.OUTBOX_WORKLOAD_CHANNEL_BUDGET_MS,
                retry_base_key=ConfigKey.OUTBOX_WORKLOAD_CHANNEL_RETRY_BASE_SECONDS,
                retry_max_key=ConfigKey.OUTBOX_WORKLOAD_CHANNEL_RETRY_MAX_SECONDS,
            )
        }
        return task

    def test_rows_are_sent_and_deleted_whatever_the_mirror_flag_says(self):
        sender = _single_sender()
        task = self._task_with_workload_sender(sender)
        row = Outbox.objects.create(job=_make_job(), channel=OutboxChannel.WORKLOAD, payload={"function_id": "j"})

        task.run()  # the flag is off: a job that was mirrored still reports its final status

        sender.send.assert_called_once_with({"function_id": "j"})
        assert not Outbox.objects.filter(pk=row.pk).exists()
