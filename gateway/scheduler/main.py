"""Scheduler loop service."""

import logging
import signal
import time

from scheduler.update_jobs_statuses import UpdateJobsStatuses
from scheduler.free_resources import FreeResources
from scheduler.schedule_queued_jobs import ScheduleQueuedJobs

logger = logging.getLogger("commands")


class Main:
    """Scheduler loop that runs all scheduler tasks."""

    def __init__(self):
        self.running = True
        self.update_jobs_statuses = UpdateJobsStatuses(self)
        self.free_resources = FreeResources(self)
        self.schedule_queued_jobs = ScheduleQueuedJobs(self)

    def run(self):
        """Run the scheduler loop."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Scheduler loop started.")

        while self.running:
            start_time = time.time()

            try:
                self.update_jobs_statuses.run()
            except Exception as ex:
                logger.exception("Error in UpdateJobsStatuses: %s", ex)

            if not self.running:
                break

            try:
                self.free_resources.run()
            except Exception as ex:
                logger.exception("Error in FreeResources: %s", ex)

            if not self.running:
                break

            try:
                self.schedule_queued_jobs.run()
            except Exception as ex:
                logger.exception("Error in ScheduleQueuedJobs: %s", ex)

            elapsed = time.time() - start_time
            if self.running and elapsed < 1:
                time.sleep(1 - elapsed)

        logger.info("Scheduler loop stopped.")

    def _handle_signal(self, signum, _frame):
        logger.info("Received signal %s, stopping scheduler loop...", signum)
        self.running = False
