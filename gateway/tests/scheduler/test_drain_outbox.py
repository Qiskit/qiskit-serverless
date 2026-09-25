"""Unit tests for DrainOutbox."""

from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from core.config_key import ConfigKey
from core.ibm_cloud.event_streams.kafka_producers import UnroutableRegionError
from core.models import Config, Job, Outbox, Program
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.drain_outbox import DrainOutbox

pytestmark = pytest.mark.django_db

_MOD = "scheduler.tasks.drain_outbox"


def _make_task(sender=None) -> DrainOutbox:
    # Config.get_int's `default=` only covers a non-numeric value, never a missing row: a key
    # with no seeded row raises KeyError. add_defaults() seeds budget_ms/breaker_failures/
    # breaker_pause_seconds from settings.DYNAMIC_CONFIG_DEFAULTS so every test can call
    # task.run() without fixing each of those three keys by hand.
    Config.add_defaults()
    Config.set(ConfigKey.OUTBOX_ENABLED, "true")
    task = DrainOutbox(KillSignal(), MagicMock(spec=SchedulerMetrics))
    if sender is not None:
        task._senders = {"billing": sender}
    return task


def _make_job() -> Job:
    from django.contrib.auth.models import User

    user, _ = User.objects.get_or_create(username="author")
    return Job.objects.create(author=user, runner=Program.FLEETS)


def _make_row(job=None, payload=None) -> Outbox:
    return Outbox.objects.create(job=job or _make_job(), channel="billing", payload=payload or {"data": {}})


class TestDisabledFlag:
    def test_returns_immediately_when_disabled(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        Config.set(ConfigKey.OUTBOX_ENABLED, "false")
        _make_row()

        task.run()

        sender.send.assert_not_called()


class TestHappyPath:
    def test_sends_and_deletes_the_row_on_success(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        row = _make_row(payload={"data": {"metric_type": "license_ibm-dev_fn_m"}})

        task.run()

        sender.send.assert_called_once_with(row.payload)
        assert not Outbox.objects.filter(pk=row.pk).exists()

    def test_sends_every_pending_row_for_the_channel(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        _make_row()
        _make_row()

        task.run()

        assert sender.send.call_count == 2
        assert Outbox.objects.count() == 0


class TestFailureHandling:
    def test_a_failure_leaves_the_row_and_records_it_on_the_breaker(self):
        sender = MagicMock()
        sender.send.side_effect = RuntimeError("kafka down")
        task = _make_task(sender=sender)
        row = _make_row()

        task.run()

        assert Outbox.objects.filter(pk=row.pk).exists()

    def test_an_unroutable_region_does_not_trip_the_breaker(self):
        sender = MagicMock()
        sender.send.side_effect = UnroutableRegionError("no region")
        task = _make_task(sender=sender)
        _make_row()
        Config.set(ConfigKey.OUTBOX_BREAKER_FAILURES, "1")

        task.run()
        task.run()  # would trip a breaker counting this as a failure; must not have

        assert sender.send.call_count == 2


class TestBreakerIsolationBetweenChannels:
    def test_one_channel_failing_does_not_stop_another_from_draining_the_same_tick(self):
        billing_sender = MagicMock()
        billing_sender.send.side_effect = RuntimeError("kafka down")
        workload_sender = MagicMock()
        task = _make_task()
        task._senders = {"billing": billing_sender, "workload": workload_sender}
        billing_row = _make_row()  # channel="billing", will fail
        workload_row = Outbox.objects.create(job=_make_job(), channel="workload", payload={})

        task.run()

        assert Outbox.objects.filter(pk=billing_row.pk).exists()  # failed, kept for retry
        assert not Outbox.objects.filter(pk=workload_row.pk).exists()  # succeeded, deleted

    def test_an_open_breaker_on_one_channel_does_not_skip_another_channel(self):
        billing_sender = MagicMock()
        billing_sender.send.side_effect = RuntimeError("kafka down")
        workload_sender = MagicMock()
        task = _make_task()
        task._senders = {"billing": billing_sender, "workload": workload_sender}
        Config.set(ConfigKey.OUTBOX_BREAKER_FAILURES, "1")
        _make_row()  # trips the billing breaker on this first run()
        task.run()
        assert task._breaker_for("billing").is_open is True

        workload_row = Outbox.objects.create(job=_make_job(), channel="workload", payload={})
        task.run()  # billing breaker open and skipped; workload must still be attempted

        workload_sender.send.assert_called_once()
        assert not Outbox.objects.filter(pk=workload_row.pk).exists()


class TestBudgetAndKillSignal:
    def test_stops_once_the_time_budget_is_spent(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        _make_row()
        _make_row()
        Config.set(ConfigKey.OUTBOX_BUDGET_MS, "0")

        with patch(f"{_MOD}.time.monotonic", side_effect=[0.0, 100.0]):
            task.run()

        sender.send.assert_not_called()

    def test_stops_between_rows_when_kill_signal_received(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        task.kill_signal.received = True
        _make_row()

        task.run()

        sender.send.assert_not_called()


class TestMultipleBatches:
    def test_keeps_fetching_until_nothing_pending(self):
        sender = MagicMock()
        task = _make_task(sender=sender)
        with patch(f"{_MOD}.BATCH_SIZE", 1):
            _make_row()
            _make_row()
            task.run()

        assert sender.send.call_count == 2
