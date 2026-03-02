"""Scheduler loop command."""

from django.core.management.base import BaseCommand

from scheduler.main import Main


class Command(BaseCommand):
    """Scheduler command to start the scheduler."""

    def handle(self, *args, **options):
        main = Main()
        main.configure()
        main.run()
