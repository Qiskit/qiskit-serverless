"""Update job status counts metric task."""

import logging

from django.db.models import Count

from core.models import Job
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.UpdateJobStatusCounts")


class UpdateJobStatusCounts(SchedulerTask):
    """Update job counts per status and provider metrics."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    def run(self):
        """Update job counts per status and provider (active states only).

        Filler jobs run continuously, so counting them here would make a constant
        floor look like user demand. They get their own gauge instead.
        """
        statuses = [Job.QUEUED, Job.PENDING, Job.RUNNING]
        active = Job.objects.filter(status__in=statuses)

        rows = active.exclude(filler=True).values("status", "program__provider__name").annotate(count=Count("id"))
        counts = {}
        for row in rows:
            status = row["status"]
            provider = row["program__provider__name"] or "custom"
            counts[(status, provider)] = row["count"]
        self.metrics.clear_job_status_counts()
        for (status, provider), count in counts.items():
            self.metrics.set_job_status_count(count, status, provider)

        filler_rows = list(active.filter(filler=True).values("status").annotate(count=Count("id")))
        self.metrics.clear_filler_jobs_counts()
        for row in filler_rows:
            self.metrics.set_filler_jobs_count(row["count"], row["status"])
