"""Unit tests for the exact worst loop and task duration gauges."""

from unittest.mock import patch

from prometheus_client import CollectorRegistry

from scheduler.metrics.duration_max_collector import WINDOW_SECONDS
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

MONOTONIC = "scheduler.metrics.duration_max_collector.time.monotonic"


class TestDurationMax:
    """Maximum duration over the last WINDOW_SECONDS."""

    def test_sample_in_window_is_the_max_and_old_one_is_dropped(self):
        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)

        with patch(MONOTONIC, return_value=1000.0):
            metrics.observe_task_duration("ScheduleFleetsJobs", 7000)
        with patch(MONOTONIC, return_value=1000.0 + WINDOW_SECONDS - 1):
            metrics.observe_task_duration("ScheduleFleetsJobs", 3)
            assert (
                registry.get_sample_value("scheduler_task_duration_max_seconds", {"task_name": "ScheduleFleetsJobs"})
                == 7000
            )
        with patch(MONOTONIC, return_value=1000.0 + WINDOW_SECONDS + 1):
            assert (
                registry.get_sample_value("scheduler_task_duration_max_seconds", {"task_name": "ScheduleFleetsJobs"})
                == 3
            )
        with patch(MONOTONIC, return_value=1000.0 + 3 * WINDOW_SECONDS):
            assert (
                registry.get_sample_value("scheduler_task_duration_max_seconds", {"task_name": "ScheduleFleetsJobs"})
                is None
            )

    def test_collector_yields_loop_and_task_gauges(self):
        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)

        metrics.observe_scheduler_iteration(5.5)
        metrics.observe_task_duration("UpdateFleetsJobsStatuses", 2.5)

        assert registry.get_sample_value("scheduler_loop_duration_max_seconds") == 5.5
        assert (
            registry.get_sample_value("scheduler_task_duration_max_seconds", {"task_name": "UpdateFleetsJobsStatuses"})
            == 2.5
        )
