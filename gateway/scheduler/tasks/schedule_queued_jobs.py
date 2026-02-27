"""Schedule queued jobs service."""

import json
import logging
import time

from concurrency.exceptions import RecordModifiedError
from django.conf import settings

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from core.config_key import ConfigKey
from core.models import ComputeResource, Job, JobEvent, Config
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from scheduler.schedule import (
    configure_job_to_use_gpu,
    get_jobs_to_schedule_fair_share,
    execute_job,
)

from scheduler.kill_signal import KillSignal
from . import SchedulerTask

logger = logging.getLogger("commands")


class ScheduleQueuedJobs(SchedulerTask):
    """Schedule jobs service."""

    def __init__(self, kill_signal: KillSignal = None):
        self.kill_signal = kill_signal or KillSignal()

    def run(self):
        """Schedule queued jobs to available cluster slots."""
        if Config.get_bool(ConfigKey.MAINTENANCE):
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        self._schedule_cpu_jobs()
        self._schedule_gpu_jobs()

    def _schedule_cpu_jobs(self):
        """Schedule CPU jobs."""
        max_clusters = settings.LIMITS_MAX_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=False).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=False)

    def _schedule_gpu_jobs(self):
        """Schedule GPU jobs."""
        max_clusters = settings.LIMITS_GPU_CLUSTERS
        running_clusters = ComputeResource.objects.filter(active=True, gpu=True).count()
        self._schedule_jobs_if_slots_available(max_clusters, running_clusters, gpu_job=True)

    def _schedule_jobs_if_slots_available(self, max_ray_clusters_possible, number_of_clusters_running, gpu_job):
        """Schedule jobs depending on free cluster slots."""
        free_clusters_slots = max_ray_clusters_possible - number_of_clusters_running
        if gpu_job:
            logger.info("%s free GPU cluster slots.", free_clusters_slots)
        else:
            logger.info("%s free CPU cluster slots.", free_clusters_slots)

        if free_clusters_slots < 1:
            # no available resources
            logger.info(
                "No clusters available. Resource consumption: %s / %s",
                number_of_clusters_running,
                max_ray_clusters_possible,
            )
            return

        # we have available resources
        jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots)

        # probably this piece of code should go in the logic for job creation
        # in the run end-point
        jobs = [configure_job_to_use_gpu(job) for job in jobs]

        # only process jobs of the appropriate compute type
        jobs = [job for job in jobs if job.gpu is gpu_job]

        for job in jobs:
            if self.kill_signal.received:
                return

            env = json.loads(job.env_vars)
            ctx = TraceContextTextMapPropagator().extract(carrier=env)

            tracer = trace.get_tracer("scheduler.tracer")
            with tracer.start_as_current_span("scheduler.handle", context=ctx):
                job = execute_job(job)
                job_id = job.id
                backup_status = job.status
                backup_logs = job.logs
                backup_resource = job.compute_resource
                backup_ray_job_id = job.ray_job_id

                succeed = False
                attempts = settings.RAY_SETUP_MAX_RETRIES

                while not succeed and attempts > 0:
                    attempts -= 1

                    try:
                        job.save()
                        # # remove artifact after successful submission and save
                        # if os.path.exists(job.program.artifact.path):
                        #     os.remove(job.program.artifact.path)

                        succeed = True
                        JobEvent.objects.add_status_event(
                            job_id=job.id,
                            origin=JobEventOrigin.SCHEDULER,
                            context=JobEventContext.SCHEDULE_JOBS,
                            status=job.status,
                        )
                    except RecordModifiedError:
                        logger.warning(
                            "Schedule: Job [%s] record has not been updated due to lock.",
                            job.id,
                        )

                        time.sleep(1)

                        job = Job.objects.get(id=job_id)
                        job.status = backup_status
                        job.logs = backup_logs
                        job.compute_resource = backup_resource
                        job.ray_job_id = backup_ray_job_id

                logger.info("Executing %s of %s", job, job.author)
        logger.info("%s are scheduled for execution.", len(jobs))
