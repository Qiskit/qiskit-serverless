"""One scheduler loop: a list of tasks run in order, over and over, in a thread of its own."""

import logging
import threading
import time

from django.db import close_old_connections, connection, connections

from scheduler.health import DB_EXCEPTIONS, SchedulerHealth
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.loop")

# A loop that finished its tasks faster than this sleeps for the rest, so an idle loop does not spin
MIN_ITERATION_SECONDS = 1


class SchedulerLoop:
    """Runs its tasks one after the other, so the order inside a loop is guaranteed, and repeats until a stop is
    requested. A slow task delays the next ones of its own loop only: the other loops have their own thread.

    Django keeps one database connection per thread, so every loop has its own, and the connection checks of the
    loop only touch that one.
    """

    def __init__(
        self,
        name: str,
        tasks: list[SchedulerTask],
        kill_signal: KillSignal,
        metrics: SchedulerMetrics,
        health: SchedulerHealth,
    ):
        self.name = name
        self.tasks = tasks
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.health = health
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Run the loop in its own thread."""
        if self._thread is not None:
            raise RuntimeError(f"Scheduler loop {self.name} already started!")
        self._thread = threading.Thread(target=self._run_in_thread, name=f"scheduler-loop-{self.name}", daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        """Whether the thread of the loop is still running."""
        return self._thread is not None and self._thread.is_alive()

    def join(self) -> None:
        """Wait for the thread of the loop to end, which it does once it sees the stop request."""
        if self._thread is not None:
            self._thread.join()

    def _run_in_thread(self) -> None:
        try:
            self.run()
        except BaseException:  # pylint: disable=broad-exception-caught
            # Nothing starts this loop again, so the process has to be restarted: the liveness probe will say so
            logger.exception("Scheduler loop %s died", self.name)
            self.health.set_loop_dead(self.name)
        finally:
            # The connection belongs to this thread and nobody else can close it
            connections.close_all()

    def run(self) -> None:
        """Run the tasks until a stop is requested."""
        logger.info("Scheduler loop %s started", self.name)
        while not self.kill_signal.received:
            start_time = time.monotonic()
            # the scheduler serves no request, so it runs Django's per-request connection check itself
            close_old_connections()

            for task in self.tasks:
                if self.kill_signal.received:
                    break
                self._run_task(task)

            elapsed = time.monotonic() - start_time

            # Store the elapsed time and the last time check
            self.metrics.observe_scheduler_iteration(self.name, elapsed)

            # don't delay more than the minimum if the loop was busy; a stop request wakes the sleep up
            if not self.kill_signal.received and elapsed < MIN_ITERATION_SECONDS:
                self.kill_signal.wait(MIN_ITERATION_SECONDS - elapsed)
        logger.info("Scheduler loop %s finished", self.name)

    def _run_task(self, task: SchedulerTask) -> None:
        task_start = time.monotonic()
        try:
            task.run()
            self.health.clear_db_error(self.name)
        except DB_EXCEPTIONS as ex:
            first_error = self.health.set_db_error(self.name)
            self.metrics.increase_task_error(task.name, ex)

            # Force-close the connection so the next task in this iteration
            # gets a fresh one rather than retrying on the same broken connection.
            connection.close()
            if first_error:
                logger.exception("Error in %s (loop %s): %s", task.name, self.name, ex)
            else:
                logger.error("DB still unavailable in %s (loop %s): %s", task.name, self.name, ex)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            self.metrics.increase_task_error(task.name, ex)
            logger.exception("Error in %s (loop %s): %s", task.name, self.name, ex)
        finally:
            self.metrics.observe_task_duration(task.name, time.monotonic() - task_start)
