"""Migrate job results to storage command."""

import logging

from django.core.management.base import BaseCommand

from core.models import Job
from core.services.storage import get_result_storage
from main import settings

logger = logging.getLogger("commands")


def save_job_results_to_storage(job: Job):
    """
    Save the result in the corresponding storage.

    Args:
        job: Job that has `result != ""`
    """

    result_storage = get_result_storage(job)
    result_storage.save(job.result)

    if not result_storage.get() in job.result:
        logger.error("Result NOT saved to storage for job [%s]", job.id)
        return False

    logger.info("Result saved to storage for job [%s]", job.id)
    return True


class Command(BaseCommand):
    """Migrate job result to storage."""

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
                .exclude(result="")[: settings.JOB_LOGS_MIGRATION_BATCH_SIZE]
            )

            if len(jobs) == 0:
                logger.info("No more jobs to process")
                break

            logger.info("Processing [%s] jobs", len(jobs))
            for job in jobs:
                if save_job_results_to_storage(job):
                    job.result = ""
                    job.save(update_fields=["result"])

                count += 1
                if max_jobs > 0 and count >= max_jobs:
                    logger.info("Reached max-jobs limit of [%s]", max_jobs)
                    return
