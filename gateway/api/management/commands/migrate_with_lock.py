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
import pglock
from django.core.management.base import BaseCommand
from django.core.management import call_command

logger = logging.getLogger("commands")


class Command(BaseCommand):
    help = "Run migrations with a PostgreSQL lock to prevent race conditions"

    LOCK_ID = "django_migrations"

    def handle(self, *args, **options):
        logger.debug("Acquiring migration lock...")

        # timeout=None waits indefinitely
        with pglock.advisory(self.LOCK_ID, timeout=None):
            logger.debug("Lock acquired, running migrations...")
            call_command("migrate", *args, **options)
            logger.debug(self.style.SUCCESS("Migrations completed successfully"))
