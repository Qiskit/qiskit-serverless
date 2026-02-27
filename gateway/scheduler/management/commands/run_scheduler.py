"""Scheduler loop command."""

import os

from django.core.management.base import BaseCommand

from scheduler.main import Main


class Command(BaseCommand):
    """Scheduler command to start the scheduler."""

    def handle(self, *args, **options):
        port = int(os.environ.get("PORT", "8002"))

        main = Main()
        main.configure()
        main.start_server(port)
        main.run()
