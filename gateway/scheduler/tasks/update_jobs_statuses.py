"""Update jobs statuses service."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.conf import settings

from core.domain.filter_logs import (
    filter_logs_with_non_public_tags,
    filter_logs_with_public_tags,
    remove_prefix_tags_in_logs,
)
from core.services.storage.logs_storage import LogsStorage
from core.utils import check_logs
from core.models import Job, JobEvent
from core.services.runners import get_runner, RunnerError
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from scheduler.schedule import (
    check_job_timeout,
    handle_job_status_not_available,
    fail_job_insufficient_resources,
)

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from .task import SchedulerTask

logger = logging.getLogger("UpdateJobsStatuses")


class UpdateJobsStatuses(SchedulerTask):
    """Update status of jobs."""

    def __init__(self, kill_signal: KillSignal = None, metrics: SchedulerMetrics = None):
        self.kill_signal = kill_signal or KillSignal()
        self.metrics = metrics or SchedulerMetrics()

    # pylint: disable=too-many-statements
    # pylint: disable=too-many-branches
    def update_job_status(self, job: Job):
        """Update status of one job."""
        if not job.compute_resource:
            logger.warning(
                "[job_id=%s Job doesn't have ComputeResource. Return false",
                job.id,
            )
            return False

        status_has_changed = False
        job_new_status = Job.PENDING
        success = False
        runner = get_runner(job)

        try:
            job_status = runner.status()
        except RunnerError as ex:
            job.status = Job.FAILED
            job.sub_status = None
            job.env_vars = "{}"
            try:
                job.save()
                JobEvent.objects.add_status_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=JobEventContext.UPDATE_JOB_STATUS,
                    status=job.status,
                )
                logger.warning(
                    "job_id=%s error=%s Error getting status, set job as FAILED",
                    job.id,
                    str(ex),
                )
            except RecordModifiedError:
                logger.warning(
                    "job_id=%s error=%s Error getting status + RecordModifiedError setting job as FAILED",
                    job.id,
                    str(ex),
                )

            return True

        if job_status:
            job_new_status = job_status
            success = True

        if check_job_timeout(job):
            job_new_status = Job.STOPPED

        if not success:
            job_new_status = handle_job_status_not_available(job, job_new_status)

        if job_new_status != job.status:
            logger.info(
                "job_id=%s author=%s Changing status from %s to %s",
                job.id,
                job.author,
                job.status,
                job_new_status,
            )
            status_has_changed = True
            job.status = job_new_status
            # cleanup env vars and save logs when job reaches terminal state
            if job.in_terminal_state():
                job.sub_status = None
                job.env_vars = "{}"
                try:
                    logs = runner.logs() or ""
                except RunnerError:
                    logs = ""
                save_logs_to_storage(job, logs)
                job.logs = ""

        try:
            logs = runner.logs()
        except RunnerError:
            logs = None

        if logs:
            # check if job is resource constrained
            no_resources_log = "No available node types can fulfill resource request"
            if no_resources_log in logs:
                job_new_status = fail_job_insufficient_resources(job)
                logger.info(
                    "job_id=%s author=%s Changing status from %s to %s because Ray error: insufficient resources",
                    job.id,
                    job.author,
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

        try:
            job.save()

            if status_has_changed:
                JobEvent.objects.add_status_event(
                    job_id=job.id,
                    origin=JobEventOrigin.SCHEDULER,
                    context=JobEventContext.UPDATE_JOB_STATUS,
                    status=job.status,
                )
        except RecordModifiedError:
            status_has_changed = False
            logger.warning("job_id=%s RecordModifiedError on save", job.id)

        return status_has_changed

    def run(self):
        """Update statuses of all running jobs."""
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        update_classical_jobs = max_ray_clusters_possible > 0
        update_gpu_jobs = max_gpu_clusters_possible > 0

        if update_classical_jobs:
            updated_jobs_counter = 0
            jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, gpu=False)
            for job in jobs:
                if self.kill_signal.received:
                    return
                if self.update_job_status(job):
                    updated_jobs_counter += 1

            if updated_jobs_counter:
                logger.info("Updated %s classical jobs.", updated_jobs_counter)

        if update_gpu_jobs:
            updated_jobs_counter = 0
            jobs = Job.objects.filter(status__in=Job.RUNNING_STATUSES, gpu=True)
            for job in jobs:
                if self.kill_signal.received:
                    return
                if self.update_job_status(job):
                    updated_jobs_counter += 1

            if updated_jobs_counter:
                logger.info("Updated %s GPU jobs.", updated_jobs_counter)


def save_logs_to_storage(job: Job, logs: str):
    """
    Save the logs in the corresponding storages.

    This function is called exactly once when a job transitions to a terminal state.

    Args:
        job: Job that has reached a terminal state
        job_handler: JobHandler to retrieve logs from Ray
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
