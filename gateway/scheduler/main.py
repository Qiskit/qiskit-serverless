"""Scheduler loop service."""

import logging
import time

from django.conf import settings
from prometheus_client import CollectorRegistry, PlatformCollector, GCCollector, ProcessCollector

from core.models import Config
from scheduler.http_server import SchedulerHttpServer
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.metrics.system_metrics_collector import SystemMetricsCollector
from scheduler.views.probes import liveness, readiness
from scheduler.kill_signal import KillSignal
from scheduler.tasks.free_resources import FreeResources
from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses

logger = logging.getLogger("main")


class Main:
    """Main scheduler loop that runs all scheduler tasks."""

    def __init__(self):
        self.kill_signal = KillSignal()
        self.kill_signal.register()  # start listening to SIGTERM and SIGINT signals
        self.http_server: SchedulerHttpServer = SchedulerHttpServer(site_host=settings.SITE_HOST)

        # Configure metrics
        self.registry = CollectorRegistry()
        self.metrics = SchedulerMetrics(registry=self.registry)
        ProcessCollector(registry=self.registry)
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        SystemMetricsCollector(registry=self.registry)

        # Write new defaults that this version might have (this is also done in the Gateway, first come, first write)
        Config.add_defaults()

        self.tasks = [
            ScheduleQueuedJobs(self.kill_signal, self.metrics),
            UpdateJobsStatuses(self.kill_signal, self.metrics),
            FreeResources(self.kill_signal, self.metrics),
        ]

    def start_http_server(self):
        """Start the internal HTTP server for probes and metrics."""
        if self.http_server.is_running():
            raise RuntimeError("Scheduler HTTP server already running!")

        self.http_server.add_path_handler("/readiness", readiness)
        self.http_server.add_path_handler("/liveness", liveness)
        self.http_server.add_path_handler("/metrics", self.metrics.metrics_app)

        self.http_server.start()

    def stop_http_server(self):
        """Stop internal HTTP server"""
        self.http_server.stop()

    def run(self):
        """Run the scheduler loop until kill signal is received."""
        logger.info("Scheduler loop started")
        try:
            while not self.kill_signal.received:
                start_time = time.time()

                for task in self.tasks:
                    if self.kill_signal.received:
                        break
                    try:
                        task.run()
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        self.metrics.increase_task_failure(task.name)
                        logger.exception("Error in %s: %s", task.name, ex)

                elapsed = time.time() - start_time

                # Store the elapsed time and the last time check
                self.metrics.observe_scheduler_iteration(elapsed, time.time())

                # don't delay more than 1s if the loop was busy
                if not self.kill_signal.received and elapsed < 1:
                    time.sleep(1 - elapsed)
        finally:
            self.stop_http_server()

        logger.info("Scheduler loop finished")
