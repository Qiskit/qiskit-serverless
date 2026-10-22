"""Scheduler loop command."""

from django.core.management.base import BaseCommand
from prometheus_client import REGISTRY
from core import external_call_metrics
from core.ibm_cloud import call_metrics
from scheduler.main import Main
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics


class Command(BaseCommand):
    """Scheduler command to start the scheduler."""

    def handle(self, *args, **options):
        metrics = SchedulerMetrics(REGISTRY)
        call_metrics.set_recorder(metrics)
        external_call_metrics.enable(REGISTRY)
        main = Main(metrics)
        main.start_http_server()
        main.run()
