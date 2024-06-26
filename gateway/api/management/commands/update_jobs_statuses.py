"""Cleanup resources command."""

import logging

from concurrency.exceptions import RecordModifiedError
from django.core.management.base import BaseCommand

from api.models import Job
from kubernetes import client as kubernetes_client, config
from kubernetes.client.exceptions import ApiException


logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Update status of jobs."""

    help = "Update running job statuses and logs."

    def handle(self, *args, **options):
        # update job statuses
        updated_jobs_counter = 0
        jobs = Job.objects.filter(status__in=Job.RUNNING_STATES)
        for job in jobs:
            job_status = Job.PENDING
            if job.compute_resource:
                # get rayjob status
                # TODO make util function
                config.load_incluster_config()
                k8s_client = kubernetes_client.api_client.ApiClient()
                ray_job_name = "rayjob-sample"  # TODO don't hardcode

                # Get cluster name
                api_instance = kubernetes_client.CustomObjectsApi(k8s_client)
                group = "ray.io"
                version = "v1"
                namespace = "default"
                plural = "rayjobs"

                try:
                    api_response = api_instance.get_namespaced_custom_object_status(
                        group, version, namespace, plural, ray_job_name
                    )
                    logger.debug(
                        f"new job status is {api_response["status"]["jobStatus"]}"
                    )
                    job_status = api_response["status"]["jobStatus"]
                except ApiException as e:
                    print("Exception when getting RayJob status: %s\n" % e)

                if job_status != job.status:
                    logger.info(
                        "Job [%s] of [%s] changed from [%s] to [%s]",
                        job.id,
                        job.author,
                        job.status,
                        job_status,
                    )
                    updated_jobs_counter += 1
                    job.status = job_status
                    # cleanup env vars
                    if job.in_terminal_state():
                        job.env_vars = "{}"

                # TODO update logs on errors?

                try:
                    job.save()
                except RecordModifiedError:
                    logger.warning(
                        "Job[%s] record has not been updated due to lock.", job.id
                    )

            else:
                logger.warning(
                    "Job [%s] does not have compute resource associated with it. Skipping.",
                    job.id,
                )

        logger.info("Updated %s jobs.", updated_jobs_counter)
