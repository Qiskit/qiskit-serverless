"""Prometheus metrics registry and helpers for scheduler lifecycle metrics."""

from prometheus_client import (
    CollectorRegistry,
    Histogram,
    Counter,
    Gauge,
    make_wsgi_app,
    ProcessCollector,
    GCCollector,
    PlatformCollector,
)

from scheduler.metrics.system_metrics_collector import SystemMetricsCollector


class SchedulerMetrics:
    """Metrics related with the scheduler life cycle like wait time per job or tasks failure.
    For system metrics (like CPU or Memory) go to the SystemMetricsCollector
    """

    def __init__(self, registry: CollectorRegistry = None):
        self.registry: CollectorRegistry = registry or CollectorRegistry()

        self.loop_duration = Histogram(
            "scheduler_loop_duration_seconds",
            "Duration of one scheduler loop iteration.",
            registry=self.registry,
        )
        self.task_failures = Counter(
            "scheduler_task_failures_total",
            "Scheduler task failures.",
            labelnames=("task_name",),
            registry=self.registry,
        )
        self.db_errors = Counter(
            "scheduler_db_errors_total",
            "Scheduler failures caused by a database connectivity error.",
            labelnames=("error_type",),
            registry=self.registry,
        )
        self.last_tick = Gauge(
            "scheduler_last_tick_timestamp_seconds",
            "Unix timestamp of latest completed scheduler loop iteration.",
            registry=self.registry,
        )
        self.queue_size = Gauge(
            "scheduler_queue_size",
            "Number of jobs currently in the queue waiting to be scheduled.",
            labelnames=("compute_type",),
            registry=self.registry,
        )
        self.queue_wait_seconds = Histogram(
            "scheduler_queue_wait_seconds",
            "Time jobs spend waiting in queue before being scheduled.",
            labelnames=("compute_type",),
            registry=self.registry,
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, float("inf")),
        )

        # from the Prometheus client library
        ProcessCollector(registry=self.registry)
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)

        # This is our personal system metrics, reading from psutil
        SystemMetricsCollector(registry=self.registry)

        self.wsgi_app = make_wsgi_app(self.registry)

    def increase_task_failure(self, task_name: str) -> None:
        """Register one scheduler task failure."""
        self.task_failures.labels(task_name=task_name).inc()

    def increase_db_error(self, error: Exception) -> None:
        """Register one scheduler failure caused by a database connectivity error."""
        self.db_errors.labels(error_type=type(error).__name__).inc()

    def observe_scheduler_iteration(self, elapsed_seconds: float, timestamp_seconds: float) -> None:
        """Register scheduler loop metrics for one full iteration."""
        self.loop_duration.observe(elapsed_seconds)
        self.last_tick.set(timestamp_seconds)

    def set_queue_size(self, size: int, compute_type: str) -> None:
        """Set current queue size for a compute type."""
        self.queue_size.labels(compute_type=compute_type).set(size)

    def observe_queue_wait_time(self, wait_seconds: float, compute_type: str) -> None:
        """Record queue wait time for a scheduled job."""
        self.queue_wait_seconds.labels(compute_type=compute_type).observe(wait_seconds)
