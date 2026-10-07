"""Unit tests for the ConsumeBlockedAccountEvents scheduler task: the drain has to fit inside a
tick of the single-threaded scheduler loop, report what it did as metrics, and stay out of the way
when Event Streams is off."""

from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry

from core.services.blocked_account_events import handle_blocked_account_event
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.consume_blocked_account_events import ConsumeBlockedAccountEvents

_MOD = "scheduler.tasks.consume_blocked_account_events"


def _task(kill_signal=None, metrics=None):
    return ConsumeBlockedAccountEvents(
        kill_signal or KillSignal(),
        metrics or SchedulerMetrics(CollectorRegistry()),
    )


def _drain_counting(*counts):
    """A drain() side effect that counts each (region, outcome) into the stats it is given."""

    def drain(_should_stop, stats):
        for region, outcome in counts:
            stats.add(region, outcome)

    return drain


def _sample(metrics, name, **labels):
    return metrics.registry.get_sample_value(name, labels) or 0


class TestConsumeBlockedAccountEventsDisabled:
    def test_no_consumer_is_built_when_event_streams_is_disabled(self, settings):
        settings.EVENT_STREAMS_ENABLED = False

        with patch(f"{_MOD}.KafkaRegionalConsumer") as mock_consumer_cls:
            task = _task()

        mock_consumer_cls.assert_not_called()
        assert task.consumer is None

    def test_run_and_close_are_noops_when_event_streams_is_disabled(self, settings):
        settings.EVENT_STREAMS_ENABLED = False

        task = _task()

        task.run()  # must not raise
        task.close()  # must not raise


class TestConsumeBlockedAccountEventsEnabled:
    def test_consumer_is_built_for_the_blocked_account_topics(self, settings):
        settings.EVENT_STREAMS_ENABLED = True
        settings.ENVIRONMENT = "production"

        with patch(f"{_MOD}.KafkaRegionalConsumer") as mock_consumer_cls:
            _task()

        mock_consumer_cls.assert_called_once_with(
            topics=[
                "quantum.production.blocked-account-plans.v1",
                "quantum.production.blocked-account-plans-non-quantum.v1",
            ],
            group_id="qiskit-serverless-scheduler-blocked-accounts-production",
            handler=handle_blocked_account_event,
        )

    def test_consumer_is_built_once_and_reused_by_every_tick(self, settings):
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaRegionalConsumer") as mock_consumer_cls:
            task = _task()
            task.run()
            task.run()
            task.run()

        mock_consumer_cls.assert_called_once()
        assert task.consumer.drain.call_count == 3

    def test_drain_is_told_about_the_kill_signal(self, settings):
        settings.EVENT_STREAMS_ENABLED = True
        kill_signal = KillSignal()

        with patch(f"{_MOD}.KafkaRegionalConsumer", return_value=MagicMock()):
            task = _task(kill_signal)
            task.run()

        should_stop, _stats = task.consumer.drain.call_args[0]
        assert should_stop() is False
        kill_signal.received = True
        assert should_stop() is True

    def test_what_the_drain_counted_becomes_metrics(self, settings):
        settings.EVENT_STREAMS_ENABLED = True
        metrics = SchedulerMetrics(CollectorRegistry())

        with patch(f"{_MOD}.KafkaRegionalConsumer", return_value=MagicMock()):
            task = _task(metrics=metrics)
        task.consumer.drain.side_effect = _drain_counting(
            ("us-east", "handled"),
            ("us-east", "handled"),
            ("eu-de", "invalid"),
            ("eu-de", "tombstone"),
            ("us-east", "consumer_error"),
            ("eu-de", "commit_error"),
            ("eu-de", "fatal"),
        )
        task.run()

        events = "scheduler_blocked_account_events_total"
        errors = "scheduler_blocked_account_consumer_errors_total"
        assert _sample(metrics, events, region="us-east", outcome="handled") == 2
        assert _sample(metrics, events, region="eu-de", outcome="invalid") == 1
        assert _sample(metrics, events, region="eu-de", outcome="tombstone") == 1
        assert _sample(metrics, errors, region="us-east", kind="consumer") == 1
        assert _sample(metrics, errors, region="eu-de", kind="commit") == 1
        assert _sample(metrics, errors, region="eu-de", kind="fatal") == 1

    def test_metrics_are_reported_even_when_the_drain_raises(self, settings):
        """A transient failure is raised for the loop to record, but what the drain did before it still counts."""
        settings.EVENT_STREAMS_ENABLED = True
        metrics = SchedulerMetrics(CollectorRegistry())

        with patch(f"{_MOD}.KafkaRegionalConsumer", return_value=MagicMock()):
            task = _task(metrics=metrics)

        def drain(_should_stop, stats):
            stats.add("us-east", "handled")
            stats.add("us-east", "retry")
            raise RuntimeError("db down")

        task.consumer.drain.side_effect = drain
        with pytest.raises(RuntimeError, match="db down"):
            task.run()

        events = "scheduler_blocked_account_events_total"
        assert _sample(metrics, events, region="us-east", outcome="handled") == 1
        assert _sample(metrics, events, region="us-east", outcome="retry") == 1

    def test_close_closes_the_consumer(self, settings):
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaRegionalConsumer", return_value=MagicMock()):
            task = _task()
            task.close()

        task.consumer.close.assert_called_once()

    def test_task_name_is_reported_for_logs_and_metrics(self, settings):
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaRegionalConsumer"):
            task = _task()

        assert task.name == "ConsumeBlockedAccountEvents"
