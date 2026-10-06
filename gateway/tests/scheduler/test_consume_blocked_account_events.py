"""Unit tests for the ConsumeBlockedAccountEvents scheduler task: the drain has to fit inside a
tick of the single-threaded scheduler loop, and stay out of the way when Event Streams is off."""

from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.consume_blocked_account_events import ConsumeBlockedAccountEvents

_MOD = "scheduler.tasks.consume_blocked_account_events"


def _task(kill_signal=None):
    return ConsumeBlockedAccountEvents(
        kill_signal or KillSignal(),
        SchedulerMetrics(CollectorRegistry()),
    )


class TestConsumeBlockedAccountEventsDisabled:
    def test_no_consumer_is_built_when_event_streams_is_disabled(self, settings):
        settings.EVENT_STREAMS_ENABLED = False

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer") as mock_consumer_cls:
            task = _task()

        mock_consumer_cls.assert_not_called()
        assert task.consumer is None

    def test_run_is_a_noop_when_event_streams_is_disabled(self, settings):
        settings.EVENT_STREAMS_ENABLED = False

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer"):
            task = _task()

        task.run()  # must not raise


class TestConsumeBlockedAccountEventsEnabled:
    def test_consumer_is_built_once_and_reused_by_every_tick(self, settings):
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer") as mock_consumer_cls:
            task = _task()
            task.run()
            task.run()
            task.run()

        mock_consumer_cls.assert_called_once()
        assert task.consumer.drain.call_count == 3

    def test_run_drains_and_returns(self, settings):
        """No thread, no join: the task returns so the rest of the loop keeps running."""
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer", return_value=MagicMock()):
            task = _task()
            task.run()

        task.consumer.drain.assert_called_once()

    def test_drain_is_told_about_the_kill_signal(self, settings):
        settings.EVENT_STREAMS_ENABLED = True
        kill_signal = KillSignal()

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer", return_value=MagicMock()):
            task = _task(kill_signal)
            task.run()

        (should_stop,) = task.consumer.drain.call_args[0]
        assert should_stop() is False
        kill_signal.received = True
        assert should_stop() is True

    def test_task_name_is_reported_for_logs_and_metrics(self, settings):
        settings.EVENT_STREAMS_ENABLED = True

        with patch(f"{_MOD}.KafkaBlockedAccountsConsumer"):
            task = _task()

        assert task.name == "ConsumeBlockedAccountEvents"
