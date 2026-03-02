"""Scheduler loop service."""

import logging
import time

from core.models import Config
from scheduler.kill_signal import KillSignal
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses
from scheduler.tasks.free_resources import FreeResources
from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs

logger = logging.getLogger("main")


class Main:
    """Main scheduler loop that runs all scheduler tasks."""

    def __init__(self):
        self.kill_signal = KillSignal()
        self.update_jobs_statuses = UpdateJobsStatuses(self.kill_signal)
        self.free_resources = FreeResources(self.kill_signal)
        self.schedule_queued_jobs = ScheduleQueuedJobs(self.kill_signal)

    def configure(self):
        """Configure the scheduler."""
        self.kill_signal.register()

        Config.add_defaults()

        logger.info("Scheduler loop started.")

    def run(self):
        """Run the scheduler loop."""

        tasks = [
            self.update_jobs_statuses,
            self.free_resources,
            self.schedule_queued_jobs,
        ]

        while not self.kill_signal.received:
            start_time = time.time()

            for task in tasks:
                if self.kill_signal.received:
                    break
                try:
                    task.run()
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    logger.exception("Error in %s: %s", task.name, ex)

            elapsed = time.time() - start_time
            if not self.kill_signal.received and elapsed < 1:
                time.sleep(1 - elapsed)

        logger.info("Scheduler loop stopped.")
