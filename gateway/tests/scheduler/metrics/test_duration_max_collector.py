"""Unit tests for the exact worst loop and task duration gauges."""

from unittest.mock import patch

from prometheus_client import CollectorRegistry

from scheduler.metrics.duration_max_collector import WINDOW_SECONDS
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics

MONOTONIC = "scheduler.metrics.duration_max_collector.time.monotonic"


def test_the_max_of_the_window_is_reported_and_old_samples_are_dropped():
    registry = CollectorRegistry()
    metrics = SchedulerMetrics(registry)
    task = {"task_name": "UpdateFleetsJobsStatuses"}

    with patch(MONOTONIC, return_value=1000.0):
        metrics.observe_task_duration("UpdateFleetsJobsStatuses", 7000)
        metrics.observe_scheduler_iteration(7100)
    with patch(MONOTONIC, return_value=1000.0 + WINDOW_SECONDS - 1):
        metrics.observe_task_duration("UpdateFleetsJobsStatuses", 3)
        assert registry.get_sample_value("scheduler_task_duration_max_seconds", task) == 7000
        assert registry.get_sample_value("scheduler_loop_duration_max_seconds") == 7100
    with patch(MONOTONIC, return_value=1000.0 + WINDOW_SECONDS + 1):
        assert registry.get_sample_value("scheduler_task_duration_max_seconds", task) == 3
        assert registry.get_sample_value("scheduler_loop_duration_max_seconds") is None
    with patch(MONOTONIC, return_value=1000.0 + 3 * WINDOW_SECONDS):
        assert registry.get_sample_value("scheduler_task_duration_max_seconds", task) is None
