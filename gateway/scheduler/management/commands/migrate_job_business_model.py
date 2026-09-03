"""Migrate the old SUBSIDIZED business model of existing jobs to LICENSED."""

import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from core.domain.business_models import BusinessModel
from core.models import Job

logger = logging.getLogger("commands")

DEFAULT_BATCH_SIZE = 500
DEFAULT_SLEEP_SECONDS = 1.0


class Command(BaseCommand):
    """Rewrite api_job.business_model from SUBSIDIZED to LICENSED in batches."""

    help = (
        "Rewrite api_job.business_model from SUBSIDIZED to LICENSED in batches, with a "
        "pause between them, so a table with a long job history is not touched by one "
        "long write. Safe to interrupt and run again: each batch only selects rows that "
        "still hold the old name, so a second run picks up where the first one stopped. "
        "Use --dry-run first to see how many rows would move."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Rows to update per batch. Default {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=DEFAULT_SLEEP_SECONDS,
            help=f"Seconds to wait between batches. Default {DEFAULT_SLEEP_SECONDS}.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report how many rows would be updated, without writing.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        sleep_seconds = options["sleep"]
        dry_run = options["dry_run"]

        if batch_size < 1:
            raise CommandError(f"--batch-size must be at least 1, got {batch_size}")
        if sleep_seconds < 0:
            raise CommandError(f"--sleep must be non-negative, got {sleep_seconds}")

        pending = Job.objects.filter(business_model=BusinessModel.SUBSIDIZED)
        total = pending.count()
        logger.info("[migrate_job_business_model] %s jobs still hold %s", total, BusinessModel.SUBSIDIZED)

        if dry_run:
            logger.info("[migrate_job_business_model] Dry run, nothing written")
            return

        updated = 0
        while True:
            affected = Job.objects.filter(id__in=pending.values_list("id")[:batch_size]).update(
                business_model=BusinessModel.LICENSED, version=F("version") + 1
            )
            if not affected:
                break

            updated += affected
            logger.info("[migrate_job_business_model] Updated %s of %s jobs", updated, total)

            if affected < batch_size:
                break

            time.sleep(sleep_seconds)

        remaining = pending.count()
        if remaining:
            raise CommandError(f"{remaining} jobs still hold {BusinessModel.SUBSIDIZED} after {updated} updated")

        logger.info("[migrate_job_business_model] Finished, %s jobs updated", updated)
