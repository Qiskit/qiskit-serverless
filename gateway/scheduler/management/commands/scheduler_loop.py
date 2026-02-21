"""Scheduler loop command."""

from django.core.management.base import BaseCommand

from scheduler.main import Main


class Command(BaseCommand):
    """Scheduler loop command that runs all scheduler tasks."""

    def handle(self, *args, **options):
        Main().run()
