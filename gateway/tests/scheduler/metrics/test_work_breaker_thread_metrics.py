"""Unit tests for the work-per-task, jobs skipped by a breaker and thread count metrics."""

from prometheus_client import CollectorRegistry

from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.metrics.system_metrics_collector import SystemMetricsCollector


class TestTaskItems:
    """Items handled by a task in a tick."""

    def test_items_are_counted_per_task_and_zero_is_ignored(self):
        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)

        metrics.increment_task_items("ScheduleFleetsJobs", 3)
        metrics.increment_task_items("ScheduleFleetsJobs", 0)

        assert registry.get_sample_value("scheduler_task_items_total", {"task_name": "ScheduleFleetsJobs"}) == 3


class TestJobsSkippedByBreaker:
    """The jobs a Code Engine breaker keeps queued."""

    def test_skipped_jobs_are_labeled_by_region(self):
        registry = CollectorRegistry()
        metrics = SchedulerMetrics(registry)

        metrics.increment_fleets_jobs_skipped_by_breaker("eu-de", 2)

        assert registry.get_sample_value("scheduler_fleets_jobs_skipped_by_breaker_total", {"region": "eu-de"}) == 2


class TestProcessThreads:
    """Live threads of the process."""

    def test_system_collector_reports_live_threads(self):
        registry = CollectorRegistry()
        SystemMetricsCollector(registry)

        assert registry.get_sample_value("scheduler_process_threads") >= 1
