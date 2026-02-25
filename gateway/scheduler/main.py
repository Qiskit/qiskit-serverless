"""Scheduler loop service."""

import logging
import time

from core.models import Config
from scheduler.kill_signal import KillSignal
from scheduler.update_jobs_statuses import UpdateJobsStatuses
from scheduler.free_resources import FreeResources
from scheduler.schedule_queued_jobs import ScheduleQueuedJobs

logger = logging.getLogger("main")


class Main:
    """Main scheduler loop that runs all scheduler tasks."""

    def __init__(self):
        self.kill_signal = KillSignal()

    def configure(self):
        """Configure the scheduler."""
        self.kill_signal.register()

        Config.add_defaults()

        logger.info("Scheduler loop started.")

    def _should_stop(self):
        return self.kill_signal.running

    def run(self):
        """Run the scheduler loop."""
        update_jobs_statuses = UpdateJobsStatuses(self.kill_signal)
        free_resources = FreeResources(self.kill_signal)
        schedule_queued_jobs = ScheduleQueuedJobs(self.kill_signal)

        tasks = [
            (update_jobs_statuses, "UpdateJobsStatuses"),
            (free_resources, "FreeResources"),
            (schedule_queued_jobs, "ScheduleQueuedJobs"),
        ]

        while self._should_stop():
            start_time = time.time()

            for task, name in tasks:
                try:
                    task.run()
                except Exception as ex:  # pylint: disable=broad-exception-caught
                    logger.exception("Error in %s: %s", name, ex)
                if not self._should_stop():
                    break

            elapsed = time.time() - start_time
            if self._should_stop() and elapsed < 1:
                time.sleep(1 - elapsed)

        logger.info("Scheduler loop stopped.")
