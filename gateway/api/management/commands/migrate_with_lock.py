"""
Django management command that runs migrations with a PostgreSQL advisory lock.

Django does not lock the database during migrations by design. So, when multiple
instances run migrations simultaneously, only the first one succeeds, but the other
ones could show errors like "column already exists" but the final database state
is correct.

This command uses pglock to ensure only one migration is executed at the same time, avoiding
confusing error messages in logs when running multiple scheduler/gateway pods.
"""

import logging
import time
import pglock
from django.core.management.base import BaseCommand
from django.core.management import call_command

logger = logging.getLogger("commands")


class Command(BaseCommand):
    """Run migrations with a PostgreSQL lock to prevent race conditions."""

    help = "Run migrations with a PostgreSQL lock to prevent race conditions"

    def handle(self, *args, **options):
        logger.debug("Acquiring migration lock...")

        start = time.time()
        # timeout=None waits indefinitely
        with pglock.advisory("django_migrations", timeout=None):
            logger.info("Lock acquired after %.2fs", time.time() - start)

            call_command("migrate", *args, **options)

            logger.info("Migrations completed successfully")
