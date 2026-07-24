"""Update Ray jobs statuses service."""

import itertools
import logging
from collections import deque
from datetime import datetime, timezone

from django.conf import settings
from django.db.models import F

from core.services.runners.ray_runner import FilteredLogs
from core.services.storage import get_logs_storage
from core.models import Job, JobEvent, Program
from core.services.runners import get_runner, RunnerError
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from scheduler.schedule import (
    check_job_timeout,
    fail_job_insufficient_resources,
)

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("scheduler.UpdateRayJobsStatuses")


def _deque_from_str(text: str) -> deque:
    return deque(text.split("\n"))


class UpdateRayJobsStatuses(SchedulerTask):
    """Update status of Ray jobs."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    # pylint: disable=too-many-statements
    # pylint: disable=too-many-branches
    def update_job_status(self, job: Job):
        """Update status of one Ray job."""
        if not job.compute_resource:
            logger.warning(
                "job_id=%s Job doesn't have ComputeResource. Return false",
                job.id,
            )
            return False

        runner = get_runner(job)

        try:
            job_new_status = runner.status()
        except RunnerError as ex:
            job.status = Job.FAILED
            job.sub_status = None
            job.env_vars = "{}"
            Job.objects.filter(pk=job.id).update(
                status=job.status, sub_status=job.sub_status, env_vars=job.env_vars, version=F("version") + 1
            )
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=job.status,
            )
            self._increment_terminal_counter(job)
            logger.warning(
                "job_id=%s error=%s Error getting status, set job as FAILED",
                job.id,
                str(ex),
            )
            return True

        status_has_changed = False
        lines: FilteredLogs | None = None
        if check_job_timeout(job):
            job_new_status = Job.STOPPED

        if job_new_status != job.status:
            logger.info(
                "job_id=%s user_id=%s Changing status from %s to %s",
                job.id,
                job.author.id,
                job.status,
                job_new_status,
            )
            status_has_changed = True
            job.status = job_new_status
            if job.in_terminal_state():
                job.sub_status = None
                job.env_vars = "{}"
                # Ray logs need fetching and persisting when the job finishes
                try:
                    lines = runner.logs()
                except RunnerError:
                    lines = FilteredLogs(public_logs=_deque_from_str("Error getting logs"), private_logs=None)
                save_logs_to_storage(job, lines)
                if job.status == Job.SUCCEEDED:
                    self._record_execution_duration(job)

        if not job.in_terminal_state():
            try:
                lines = runner.logs()
            except RunnerError:
                lines = FilteredLogs(public_logs=_deque_from_str("Error getting logs"), private_logs=None)

        if lines is not None:
            # check if job is resource constrained
            no_resources_log = "No available node types can fulfill resource request"
            all_lines = itertools.chain(lines.public_logs, lines.private_logs or [])
            if any(no_resources_log in line for line in all_lines):
                job_new_status = fail_job_insufficient_resources(job)
                logger.info(
                    "job_id=%s user_id=%s Changing status from %s to %s because Ray error: insufficient resources",
                    job.id,
                    job.author.id,
                    job.status,
                    job_new_status,
                )
                lines = FilteredLogs(
                    public_logs=deque(
                        [
                            "Insufficient resources available to the run job in this "
                            "configuration.\nMax resources allowed are "
                            f"{settings.LIMITS_CPU_PER_TASK} CPUs and "
                            f"{settings.LIMITS_MEMORY_PER_TASK} GB of RAM per job."
                        ]
                    ),
                    private_logs=None,
                )
                job.status = job_new_status
                job.env_vars = "{}"
                status_has_changed = True
                save_logs_to_storage(job, lines)

        if status_has_changed:
            Job.objects.filter(pk=job.id).update(
                status=job.status,
                sub_status=job.sub_status,
                env_vars=job.env_vars,
                version=F("version") + 1,
            )
            job.refresh_from_db(fields=["version"])
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.SCHEDULER,
                context=JobEventContext.UPDATE_JOB_STATUS,
                status=job.status,
            )
            if job.in_terminal_state():
                self._increment_terminal_counter(job)

        return status_has_changed

    def _increment_terminal_counter(self, job: Job) -> None:
        """Increment terminal jobs counter."""
        provider = job.program.provider.name if job.program_id and job.program.provider_id else "custom"
        self.metrics.increment_jobs_terminal(provider=provider, final_status=job.status)

    def _record_execution_duration(self, job: Job) -> None:
        """Record execution duration for a successfully completed job."""
        running_event = JobEvent.objects.filter(job=job, data__status=Job.RUNNING).order_by("-created").first()
        if running_event is None:
            return
        duration = (datetime.now(timezone.utc) - running_event.created).total_seconds()
        provider = job.program.provider.name if job.program_id and job.program.provider_id else "custom"
        self.metrics.observe_job_execution_duration(duration, provider)

    def run(self):
        """Update statuses of all running Ray jobs."""
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        update_ray_jobs = max_ray_clusters_possible > 0
        update_gpu_jobs = max_gpu_clusters_possible > 0

        ray_counter = 0
        gpu_counter = 0
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES).exclude(runner=Program.FLEETS)
        for job in jobs:
            if self.kill_signal.received:
                return
            if job.gpu and update_gpu_jobs:
                if self.update_job_status(job):
                    gpu_counter += 1
            elif not job.gpu and update_ray_jobs:
                if self.update_job_status(job):
                    ray_counter += 1

        if ray_counter:
            logger.info("Updated %s classical jobs.", ray_counter)
        if gpu_counter:
            logger.info("Updated %s GPU jobs.", gpu_counter)


def save_logs_to_storage(job: Job, logs: FilteredLogs):
    """Save Ray job logs to the local filesystem (COS-mounted volume).

    Called once when a Ray job transitions to a terminal state. The logs are
    already filtered and prefix-stripped inside FilteredLogs; this function
    only joins the lines and writes them to storage.

    Args:
        job: Job that has reached a terminal state.
        logs: FilteredLogs from _stream_logs_from_ray(), already filtered.
    """
    logs_storage = get_logs_storage(job)
    public_content = "\n".join(logs.public_logs) + "\n" if logs.public_logs else ""
    if job.program.provider:
        logs_storage.save_public_logs(public_content)
        logger.info("job_id=%s Provider function. Public logs saved to storage", job.id)
        private_content = "\n".join(logs.private_logs) + "\n" if logs.private_logs else ""
        logs_storage.save_private_logs(private_content)
        logger.info("job_id=%s Provider function. Private logs saved to storage", job.id)
    else:
        logs_storage.save_public_logs(public_content)
        logger.info("job_id=%s Custom function. Public logs saved to storage", job.id)
