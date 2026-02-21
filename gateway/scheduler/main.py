"""Scheduler loop service."""

import logging
import signal
import time

from scheduler.update_jobs_statuses import UpdateJobsStatuses
from scheduler.free_resources import FreeResources
from scheduler.schedule_queued_jobs import ScheduleQueuedJobs

logger = logging.getLogger("main")


class Main:
    """Main scheduler loop that runs all scheduler tasks."""

    def __init__(self):
        self.running = True

    def run(self):
        """Run the scheduler loop."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Scheduler loop started.")

        update_jobs_statuses = UpdateJobsStatuses(self)
        free_resources = FreeResources(self)
        schedule_queued_jobs = ScheduleQueuedJobs(self)

        tasks = [
            (update_jobs_statuses, "UpdateJobsStatuses"),
            (free_resources, "FreeResources"),
            (schedule_queued_jobs, "ScheduleQueuedJobs"),
        ]

        while self.running:
            start_time = time.time()

            for task, name in tasks:
                try:
                    task.run()
                except Exception as ex:
                    logger.exception("Error in %s: %s", name, ex)
                if not self.running:
                    break

            elapsed = time.time() - start_time
            if self.running and elapsed < 1:
                time.sleep(1 - elapsed)

        logger.info("Scheduler loop stopped.")

    def _handle_signal(self, signum, _frame):
        logger.info("Received signal %s, stopping scheduler loop...", signum)
        self.running = False
