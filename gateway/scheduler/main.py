"""Scheduler loop service."""

import logging
import time

from core.models import Config
from scheduler.http_server import SchedulerHttpServer
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
        self.tasks = [
            UpdateJobsStatuses(self.kill_signal),
            FreeResources(self.kill_signal),
            ScheduleQueuedJobs(self.kill_signal),
        ]
        self.http_server: SchedulerHttpServer = None

    def configure(self):
        """Configure the scheduler."""
        self.kill_signal.register()
        Config.add_defaults()
        logger.info("Scheduler loop started.")

    def start_server(self, port: int):
        """Start internal HTTP server for probes and metrics if configured."""

        self.http_server = SchedulerHttpServer(port=port)
        self.http_server.add_json_handler("/readiness", readiness)
        self.http_server.add_json_handler("/liveness", liveness)
        self.http_server.start()

    def run(self):
        """Run the scheduler loop."""
        try:
            while not self.kill_signal.received:
                start_time = time.time()

                for task in self.tasks:
                    if self.kill_signal.received:
                        break
                    try:
                        task.run()
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        logger.exception("Error in %s: %s", task.name, ex)

                elapsed = time.time() - start_time
                if not self.kill_signal.received and elapsed < 1:
                    time.sleep(1 - elapsed)
        finally:
            if self.http_server:
                self.http_server.stop()
            logger.info("Scheduler loop stopped.")
