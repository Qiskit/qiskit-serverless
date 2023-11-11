"""Job entry update handler."""
import json
import logging
import time

from concurrency.exceptions import RecordModifiedError
from django.conf import settings

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from api.models import ComputeResource, Job
from api.schedule import get_jobs_to_schedule_fair_share, execute_job
from api.ray import kill_ray_cluster
from main import settings as config


logger = logging.getLogger("gateway")


def throttle_job(job):
    """throttle jobs."""

    max_limit = 100
    all_running_jobs = Job.objects.filter(status__in=Job.RUNNING_STATES)
    if all_running_jobs.count() >= max_limit:
        return None

    running_jobs = all_running_jobs.filter(author__exact=job.author)
    if running_jobs.count() >= settings.LIMITS_JOBS_PER_USER:
        return None
    queued_job = Job.objects.filter(
        status=Job.QUEUED, author__exact=job.author
    ).order_by("created")[:1]
    if queued_job.count() == 0:
        return None
    return queued_job[0]


def release_job():
    """release job"""
    jobs = get_jobs_to_schedule_fair_share(1)
    if len(jobs) != 0:
        return jobs[0]
    return None


def schedule_job(job_id):
    """schedule a job."""
    job = Job.objects.get(id=job_id)
    job = throttle_job(job)
    if not job:
        return
    # only for local mode
    if settings.RAY_CLUSTER_MODE.get("local") and settings.RAY_CLUSTER_MODE.get(
        "ray_local_host"
    ):
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
                # remove artifact after successful submission and save
                # if os.path.exists(job.program.artifact.path):
                #     os.remove(job.program.artifact.path)

                succeed = True
            except RecordModifiedError:
                logger.warning(
                    "Schedule: Job[%s] record has not been updated due to lock.",
                    job.id,
                )

                time.sleep(1)

                job = Job.objects.get(id=job_id)
                job.status = backup_status
                job.logs = backup_logs
                job.compute_resource = backup_resource
                job.ray_job_id = backup_ray_job_id

            logger.info("Executing %s of %s", job, job.author)


def remove_resource(job_id):
    """remove resource."""
    job = Job.objects.get(id=job_id)
    compute_resource = job.compute_resource

    alive_jobs = Job.objects.filter(
        status__in=Job.RUNNING_STATES, compute_resource=compute_resource
    )

    # only kill cluster if not in local mode and no jobs are running there
    if len(alive_jobs) == 0 and not settings.RAY_CLUSTER_MODE.get("local"):
        if config.RAY_CLUSTER_NO_DELETE_ON_COMPLETE:
            logger.debug(
                "RAY_CLUSTER_NO_DELETE_ON_COMPLETE is enabled, "
                + "so cluster [%s] will not be removed",
                compute_resource.title,
            )
            return
        kill_ray_cluster(compute_resource.title)
        # deactivate
        compute_resource.active = False
        compute_resource.save()
        logger.info(
            "Cluster [%s] is free after usage from [%s]",
            compute_resource.title,
            compute_resource.owner,
        )
    job = release_job()
    if job:
        schedule_job(job.id)
