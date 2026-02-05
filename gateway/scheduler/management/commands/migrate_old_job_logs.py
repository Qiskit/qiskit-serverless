"""Cleanup resources command."""

import logging

from django.core.management.base import BaseCommand

from api.domain.function import check_logs
from api.models import Job
from api.services.storage.logs_storage import LogsStorage
from main import settings

logger = logging.getLogger("commands")


def save_job_logs_to_storage(job: Job):
    """
    Save the logs in the corresponding storages.

    Args:
        job: Job that has reached a terminal state and has `logs != ""`
    """

    logs = check_logs(job.logs, job)

    logs_storage = LogsStorage(job)
    if job.program.provider:
        logs_storage.save_private_logs(logs)
    else:
        logs_storage.save_public_logs(logs)

    logger.info("Logs saved to storage for job [%s]", job.id)


class Command(BaseCommand):
    """Cleanup resources."""

    def handle(self, *args, **options):
        jobs = list()
        while True:
            jobs = list(
                Job.objects.order_by("id")
                .filter(
                    status__in=Job.TERMINAL_STATUSES, compute_resource__active=False
                )
                .exclude(logs="")[: settings.JOB_LOGS_MIGRATION_BATCH_SIZE]
            )

            if len(jobs) == 0:
                logger.info("No more jobs to process")
                break

            logger.info("Processing [%s] jobs", len(jobs))
            for job in jobs:
                save_job_logs_to_storage(job)

                job.logs = ""
                job.save(update_fields=["logs"])
