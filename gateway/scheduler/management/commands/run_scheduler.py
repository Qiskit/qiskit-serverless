"""Scheduler loop command."""

from django.core.management.base import BaseCommand
from prometheus_client import REGISTRY
from scheduler.main import Main
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics


class Command(BaseCommand):
    """Scheduler command to start the scheduler."""

    def handle(self, *args, **options):
        main = Main(SchedulerMetrics(REGISTRY))
        main.start_http_server()
        main.run()
