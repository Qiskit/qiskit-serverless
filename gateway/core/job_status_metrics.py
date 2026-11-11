"""How long a job stays in each status, recorded by the scheduler when the job leaves it."""

from datetime import datetime

from prometheus_client import REGISTRY, CollectorRegistry, Histogram

_DURATION: Histogram | None = None


def enable(registry: CollectorRegistry = REGISTRY) -> None:
    """Start recording in ``registry``."""
    global _DURATION  # pylint: disable=global-statement
    _DURATION = Histogram(
        "scheduler_job_status_duration_seconds",
        "Time a job spent in a status, by the status it left and the status it went to. Filler jobs are left out.",
        labelnames=("status", "final_status", "compute_type"),
        buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200, 14400, 28800, 43200, 86400, float("inf")),
        registry=registry,
    )


def disable() -> None:
    """Stop recording. For tests."""
    global _DURATION  # pylint: disable=global-statement
    _DURATION = None


def enabled() -> bool:
    """Whether this process records."""
    return _DURATION is not None


def observe(status: str, final_status: str, gpu: bool, entered: datetime, left: datetime) -> None:
    """Record that a job left ``status`` for ``final_status``, if recording is enabled."""
    if _DURATION is not None:
        _DURATION.labels(status=status, final_status=final_status, compute_type="gpu" if gpu else "cpu").observe(
            (left - entered).total_seconds()
        )
