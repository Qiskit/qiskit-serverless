"""Scheduler loop service."""

import logging
import time

from django.conf import settings
from django.db import connection

from core.models import Config
from scheduler.health import DB_EXCEPTIONS, SchedulerHealth
from scheduler.http_server import SchedulerHttpServer
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.kill_signal import KillSignal
from scheduler.tasks.free_resources import FreeResources
from scheduler.tasks.schedule_queued_jobs import ScheduleQueuedJobs
from scheduler.tasks.update_jobs_statuses import UpdateJobsStatuses

logger = logging.getLogger("scheduler.main")


class Main:
    """Main scheduler loop that runs all scheduler tasks."""

    def __init__(self, metrics: SchedulerMetrics):
        self.kill_signal = KillSignal()
        self.kill_signal.register()  # start listening to SIGTERM and SIGINT signals

        self.metrics = metrics
        self.health = SchedulerHealth()
        self.http_server: SchedulerHttpServer = SchedulerHttpServer(site_host=settings.SITE_HOST)
        self.http_server.configure_routes(self.metrics, self.health)

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
                # The scheduler is single-threaded and reuses the same DB connection indefinitely.
                # Closing it unconditionally at the start of each iteration ensures the next DB
                # access always creates a fresh connection, avoiding stale/dropped connections.
                connection.close()

                for task in self.tasks:
                    if self.kill_signal.received:
                        break
                    task_start = time.time()
                    try:
                        task.run()
                        self.health.clear_db_error()
                    except DB_EXCEPTIONS as ex:
                        first_error = self.health.set_db_error()
                        self.metrics.increase_task_error(task.name, ex)

                        # Force-close the connection so the next task in this iteration
                        # gets a fresh one rather than retrying on the same broken connection.
                        connection.close()
                        if first_error:
                            logger.exception("Error in %s: %s", task.name, ex)
                        else:
                            logger.error("DB still unavailable in %s: %s", task.name, ex)
                    except Exception as ex:  # pylint: disable=broad-exception-caught
                        self.metrics.increase_task_error(task.name, ex)
                        logger.exception("Error in %s: %s", task.name, ex)
                    finally:
                        self.metrics.observe_task_duration(task.name, time.time() - task_start)

                elapsed = time.time() - start_time

                # Store the elapsed time and the last time check
                self.metrics.observe_scheduler_iteration(elapsed)

                # don't delay more than 1s if the loop was busy
                if not self.kill_signal.received and elapsed < 1:
                    time.sleep(1 - elapsed)
        finally:
            self.stop_http_server()

        logger.info("Scheduler loop finished")
