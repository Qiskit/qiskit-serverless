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
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command

logger = logging.getLogger("migrate_with_lock")

POLL_SECONDS = 2
DEFAULT_LOCK_TIMEOUT_SECONDS = 900


class Command(BaseCommand):
    """Run migrations with a PostgreSQL lock to prevent race conditions."""

    help = "Run migrations with a PostgreSQL lock to prevent race conditions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--lock-timeout",
            type=float,
            default=DEFAULT_LOCK_TIMEOUT_SECONDS,
            help="Seconds to wait for the migration lock before failing (default: %(default)s)",
        )

    def handle(self, *args, **options):
        lock_timeout = options.pop("lock_timeout")
        logger.debug("Acquiring migration lock...")

        start = time.monotonic()
        while True:
            # timeout=0 uses pg_try_advisory_lock, which returns at once. Waiting inside a blocking
            # lock statement would keep a transaction open, and CREATE INDEX CONCURRENTLY in the
            # migrating container waits for those, so the two would deadlock.
            with pglock.advisory("django_migrations", timeout=0) as acquired:
                if acquired:
                    logger.info("Lock acquired after %.2fs", time.monotonic() - start)

                    call_command("migrate", *args, **options)

                    logger.info("Migrations completed successfully")
                    return
            if time.monotonic() - start >= lock_timeout:
                raise CommandError(f"Could not acquire the migration lock after {lock_timeout:g}s")
            time.sleep(POLL_SECONDS)
