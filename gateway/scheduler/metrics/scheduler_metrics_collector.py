"""Prometheus metrics registry and helpers for scheduler lifecycle metrics."""

from prometheus_client import (
    CollectorRegistry,
    Histogram,
    Counter,
    Gauge,
    make_wsgi_app,
)

from scheduler.metrics.system_metrics_collector import SystemMetricsCollector


class SchedulerMetrics:  # pylint: disable=too-many-instance-attributes
    """Metrics related with the scheduler life cycle like wait time per job or tasks failure.
    For system metrics (like CPU or Memory) go to the SystemMetricsCollector
    """

    def __init__(self, registry: CollectorRegistry):
        self.registry: CollectorRegistry = registry

        self.loop_duration = Histogram(
            "scheduler_loop_duration_seconds",
            "Duration of one scheduler loop iteration.",
            registry=self.registry,
        )
        self.task_errors = Counter(
            "scheduler_task_errors_total",
            "Scheduler task errors.",
            labelnames=("task_name", "error_type"),
            registry=self.registry,
        )
        self.task_duration = Histogram(
            "scheduler_task_duration_seconds",
            "Duration of one scheduler task execution.",
            labelnames=("task_name",),
            registry=self.registry,
        )
        self.start_time = Gauge(
            "scheduler_start_timestamp_seconds",
            "Unix timestamp when the scheduler process started.",
            registry=self.registry,
        )
        self.start_time.set_to_current_time()

        self.last_tick = Gauge(
            "scheduler_last_tick_timestamp_seconds",
            "Unix timestamp of latest completed scheduler loop iteration.",
            registry=self.registry,
        )
        self.job_status_count = Gauge(
            "scheduler_job_status_count",
            "Number of jobs per status and provider.",
            labelnames=("status", "provider"),
            registry=self.registry,
        )
        self.jobs_terminal_total = Counter(
            "scheduler_jobs_terminal_total",
            "Total jobs that reached a terminal state (SUCCEEDED, FAILED, STOPPED).",
            labelnames=("provider", "final_status"),
            registry=self.registry,
        )
        self.job_execution_duration = Histogram(
            "scheduler_job_execution_duration_seconds",
            "Time successful jobs spend executing from RUNNING to SUCCEEDED.",
            labelnames=("provider",),
            registry=self.registry,
            buckets=(30, 60, 300, 600, 1800, 3600, 7200, 14400, float("inf")),
        )
        self.queue_wait_seconds = Histogram(
            "scheduler_queue_wait_seconds",
            "Time jobs spend waiting in queue before being scheduled.",
            labelnames=("compute_type",),
            registry=self.registry,
            buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, float("inf")),
        )

        SystemMetricsCollector(registry=self.registry)

        self.wsgi_app = make_wsgi_app(self.registry)

    def increase_task_error(self, task_name: str, error: Exception) -> None:
        """Register one scheduler task error."""
        self.task_errors.labels(task_name=task_name, error_type=type(error).__name__).inc()

    def observe_task_duration(self, task_name: str, elapsed_seconds: float) -> None:
        """Record execution time for one task."""
        self.task_duration.labels(task_name=task_name).observe(elapsed_seconds)

    def observe_scheduler_iteration(self, elapsed_seconds: float) -> None:
        """Register scheduler loop metrics for one full iteration."""
        self.loop_duration.observe(elapsed_seconds)
        self.last_tick.set_to_current_time()

    def observe_queue_wait_time(self, wait_seconds: float, compute_type: str) -> None:
        """Record queue wait time for a scheduled job."""
        self.queue_wait_seconds.labels(compute_type=compute_type).observe(wait_seconds)

    def set_job_status_count(self, count: int, status: str, provider: str) -> None:
        """Set job count for a specific status and provider."""
        self.job_status_count.labels(status=status, provider=provider).set(count)

    def observe_job_execution_duration(self, duration_seconds: float, provider: str) -> None:
        """Record execution time from RUNNING to SUCCEEDED."""
        self.job_execution_duration.labels(provider=provider).observe(duration_seconds)

    def increment_jobs_terminal(self, provider: str, final_status: str) -> None:
        """Increment counter when a job reaches a terminal state."""
        self.jobs_terminal_total.labels(provider=provider, final_status=final_status).inc()
