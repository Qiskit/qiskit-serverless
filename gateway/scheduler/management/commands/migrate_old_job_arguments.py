"""Migrate job arguments to storage command."""

import logging

from django.core.management.base import BaseCommand

from core.models import Job
from core.services.storage import get_arguments_storage
from main import settings

logger = logging.getLogger("commands")


def save_job_arguments_to_storage(job: Job):
    """
    Save the arguments in the corresponding storage.

    Args:
        job: Job that has `arguments != ""`
    """

    arguments_storage = get_arguments_storage(job)
    arguments_storage.save(job.arguments)

    if not arguments_storage.get() in job.arguments:
        logger.error("Arguments NOT saved to storage for job [%s]", job.id)
        return False

    logger.info("Arguments saved to storage for job [%s]", job.id)
    return True


class Command(BaseCommand):
    """Migrate job arguments to storage."""

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=1,
            help="Maximum number of jobs to process. Default 0 (means unlimited)",
        )

    def handle(self, *args, **options):
        max_jobs = options["max_jobs"]
        count = 0

        while True:
            jobs = list(
                Job.objects.order_by("id")
                .filter(status__in=Job.TERMINAL_STATUSES, compute_resource__active=False)
                .exclude(arguments="")[: settings.JOB_LOGS_MIGRATION_BATCH_SIZE]
            )

            if len(jobs) == 0:
                logger.info("No more jobs to process")
                break

            logger.info("Processing [%s] jobs", len(jobs))
            for job in jobs:
                if save_job_arguments_to_storage(job):
                    job.arguments = ""
                    job.save(update_fields=["arguments"])

                count += 1
                if max_jobs > 0 and count >= max_jobs:
                    logger.info("Reached max-jobs limit of [%s]", max_jobs)
                    return
