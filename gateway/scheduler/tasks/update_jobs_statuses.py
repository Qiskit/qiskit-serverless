"""Update jobs statuses service."""

import logging
from datetime import datetime, timezone

from django.conf import settings

from core.domain.filter_logs import (
    filter_logs_with_non_public_tags,
    filter_logs_with_public_tags,
    remove_prefix_tags_in_logs,
)
from core.services.storage.logs_storage import LogsStorage
from core.utils import check_logs
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

logger = logging.getLogger("scheduler.UpdateJobsStatuses")


class UpdateJobsStatuses(SchedulerTask):
    """Update status of jobs."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics

    # pylint: disable=too-many-statements
    # pylint: disable=too-many-branches
    def update_job_status(self, job: Job):
        """Update status of one job."""
        is_fleets_job = job.runner == Program.FLEETS

        if not is_fleets_job and not job.compute_resource:
            logger.warning(
                "job_id=%s Job doesn't have ComputeResource. Return false",
                job.id,
            )
            return False

        if is_fleets_job and not job.fleet_id:
            logger.warning(
                "job_id=%s Fleets job doesn't have fleet_id. Return false",
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
            Job.objects.filter(pk=job.id).update(status=job.status, sub_status=job.sub_status, env_vars=job.env_vars)
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
            # cleanup env vars and save logs when job reaches terminal state
            if job.in_terminal_state():
                job.sub_status = None
                job.env_vars = "{}"
                # Fleets logs are already in COS; only Ray logs need fetching and persisting.
                if not is_fleets_job:
                    try:
                        logs = runner.logs() or ""
                    except RunnerError:
                        logs = ""
                    save_logs_to_storage(job, logs)
                else:
                    # For Fleets jobs, retrieve results from COS and save to database
                    try:
                        result_str = runner.get_result_from_cos()
                        if result_str:
                            job.result = result_str
                            logger.info("Retrieved and saved results for Fleets job [%s]", job.id)
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        logger.warning("Failed to retrieve results for Fleets job [%s]: %s", job.id, str(ex))
                job.logs = ""
                if job.status == Job.SUCCEEDED:
                    self._record_execution_duration(job)

        if not is_fleets_job and not job.in_terminal_state():
            try:
                logs = runner.logs()
            except RunnerError:
                logs = None

        if not is_fleets_job and logs:
            # check if job is resource constrained
            no_resources_log = "No available node types can fulfill resource request"
            if no_resources_log in logs:
                job_new_status = fail_job_insufficient_resources(job)
                logger.info(
                    "job_id=%s user_id=%s Changing status from %s to %s because Ray error: insufficient resources",
                    job.id,
                    job.author.id,
                    job.status,
                    job_new_status,
                )
                logs = (
                    "Insufficient resources available to the run job in this "
                    "configuration.\nMax resources allowed are "
                    f"{settings.LIMITS_CPU_PER_TASK} CPUs and "
                    f"{settings.LIMITS_MEMORY_PER_TASK} GB of RAM per job."
                )
                job.status = job_new_status
                # cleanup env vars
                job.env_vars = "{}"
                status_has_changed = True
                save_logs_to_storage(job, logs)
                job.logs = ""

        Job.objects.filter(pk=job.id).update(
            status=job.status,
            sub_status=job.sub_status,
            env_vars=job.env_vars,
            result=job.result,
            logs=job.logs,
        )

        if status_has_changed:
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
        """Update statuses of all running jobs."""
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        max_fleets_clusters_possible = settings.LIMITS_MAX_FLEETS
        update_ray_jobs = max_ray_clusters_possible > 0
        update_gpu_jobs = max_gpu_clusters_possible > 0
        update_fleets_jobs = max_fleets_clusters_possible > 0

        fleets_counter = 0
        ray_counter = 0
        gpu_counter = 0
        # Note: with LIMITS_MAX_FLEETS potentially reaching 1000+ concurrent jobs, updating statuses
        # sequentially will become a bottleneck. This loop should be parallelized using multiple
        # threads or batched processing for performance reasons.
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES)
        for job in jobs:
            if self.kill_signal.received:
                return
            if job.runner == Program.FLEETS and update_fleets_jobs:
                if self.update_job_status(job):
                    fleets_counter += 1
            elif job.gpu and update_gpu_jobs:
                if self.update_job_status(job):
                    gpu_counter += 1
            elif not job.gpu and update_ray_jobs:
                if self.update_job_status(job):
                    ray_counter += 1

        if fleets_counter:
            logger.info("Updated %s Fleets jobs.", fleets_counter)
        if ray_counter:
            logger.info("Updated %s classical jobs.", ray_counter)
        if gpu_counter:
            logger.info("Updated %s GPU jobs.", gpu_counter)


def save_logs_to_storage(job: Job, logs: str):
    """Save Ray job logs to the local filesystem (COS-mounted volume).

    Called once when a Ray job transitions to a terminal state. Filters the
    combined log stream into public (user) and private (provider) logs.

    This function is only used for Ray jobs. Fleets logs are written directly
    to COS by the PDS shell wrapper during execution.

    Args:
        job: Job that has reached a terminal state.
        logs: Combined log stream from Ray.
    """

    logs = check_logs(logs, job)

    logs_storage = LogsStorage(job)
    if job.program.provider:
        public_logs = filter_logs_with_public_tags(logs)
        logs_storage.save_public_logs(public_logs)
        logger.info("job_id=%s Provider function. Public logs saved to storage", job.id)
        private_logs = filter_logs_with_non_public_tags(logs)
        logs_storage.save_private_logs(private_logs)
        logger.info("job_id=%s Provider function. Private logs saved to storage", job.id)
    else:
        filtered_logs = remove_prefix_tags_in_logs(logs)
        logs_storage.save_public_logs(filtered_logs)
        logger.info("job_id=%s Custom function. Public logs saved to storage", job.id)
