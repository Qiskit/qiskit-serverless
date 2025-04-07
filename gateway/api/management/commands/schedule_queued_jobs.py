"""Cleanup resources command."""

import json
import logging
import time

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Model

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from api.models import ComputeResource, Job
from api.schedule import get_jobs_to_schedule_fair_share, execute_job

User: Model = get_user_model()
logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Schedule jobs command."""

    help = (
        "Schedule jobs that are in queued "
        "status based on availability of resources in the system."
    )

    def handle(self, *args, **options):
        max_ray_clusters_possible = settings.LIMITS_MAX_CLUSTERS
        max_gpu_clusters_possible = settings.LIMITS_GPU_CLUSTERS
        maintenance = settings.MAINTENANCE

        if maintenance:
            logger.warning("System in maintenance mode. Skipping new jobs schedule.")
            return

        number_of_clusters_running = ComputeResource.objects.filter(
            active=True, gpu=False
        ).count()
        number_of_gpu_clusters_running = ComputeResource.objects.filter(
            active=True, gpu=True
        ).count()

        self.schedule_jobs_if_slots_available(
            max_ray_clusters_possible, number_of_clusters_running, False
        )
        self.schedule_jobs_if_slots_available(
            max_gpu_clusters_possible, number_of_gpu_clusters_running, True
        )

    def schedule_jobs_if_slots_available(
        self, max_ray_clusters_possible, number_of_clusters_running, gpu_job
    ):
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
        else:
            # we have available resources
            jobs = get_jobs_to_schedule_fair_share(slots=free_clusters_slots)

            # only process jobs of the appropriate compute type
            jobs = [job for job in jobs if job.gpu is gpu_job]

            for job in jobs:
                # only for local mode
                if settings.RAY_CLUSTER_MODE.get(
                    "local"
                ) and settings.RAY_CLUSTER_MODE.get("ray_local_host"):
                    logger.info("Running in local mode")
                    compute_resource = ComputeResource.objects.filter(
                        host=settings.RAY_CLUSTER_MODE.get("ray_local_host")
                    ).first()
                    if compute_resource is None:
                        compute_resource = ComputeResource(
                            host=settings.RAY_CLUSTER_MODE.get("ray_local_host"),
                            title="Local compute resource",
                            owner=job.author,
                        )
                        compute_resource.save()
                    job.compute_resource = compute_resource
                    job.save()

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
