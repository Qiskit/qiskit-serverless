"""Scheduler loop service."""

import logging

from django.conf import settings
from django.db import connections

from core.models import Config
from core.services.background_executor import get_background_executor
from core.services.job_transitions import JobTransitionService
from core.services.workload_best_effort_mirror import WorkloadBackgroundMirror
from scheduler.schedule import FleetsBreakers, FleetsJobCanceller, FleetsJobSubmitter
from scheduler.health import SchedulerHealth
from scheduler.http_server import SchedulerHttpServer
from scheduler.loop import SchedulerLoop
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.kill_signal import KillSignal
from scheduler.tasks.balance_filler_jobs import BalanceFillerJobs
from scheduler.tasks.consume_blocked_account_events import ConsumeBlockedAccountEvents
from scheduler.tasks.export_fleets_breakers import ExportFleetsBreakers
from scheduler.tasks.free_fleets_resources import FreeFleetsResources
from scheduler.tasks.free_ray_resources import FreeRayResources
from scheduler.tasks.outbox import OutboxTask
from scheduler.tasks.schedule_fleets_jobs import ScheduleFleetsJobs
from scheduler.tasks.schedule_ray_jobs import ScheduleRayJobs
from scheduler.tasks.stop_blocked_fleets_jobs import StopBlockedFleetsJobs
from scheduler.tasks.task import SchedulerTask
from scheduler.tasks.update_fleets_jobs_statuses import UpdateFleetsJobsStatuses
from scheduler.tasks.update_job_status_counts import UpdateJobStatusCounts
from scheduler.tasks.update_ray_jobs_statuses import UpdateRayJobsStatuses

logger = logging.getLogger("scheduler.main")


class Main:
    """Starts the scheduler loops, each one in a thread of its own, and waits for the kill signal.

    A slow task only delays the tasks of its own loop. The Ray tasks, the Fleets submits, the Fleets status updates and
    the housekeeping tasks do not wait for each other.
    """

    def __init__(self, metrics: SchedulerMetrics):
        self.kill_signal = KillSignal()
        self.kill_signal.register()  # start listening to SIGTERM and SIGINT signals

        self.metrics = metrics
        self.health = SchedulerHealth()
        self.http_server: SchedulerHttpServer = SchedulerHttpServer(site_host=settings.SITE_HOST)
        self.http_server.configure_routes(self.metrics, self.health)

        # Write new defaults that this version might have (this is also done in the Gateway, first come, first write)
        Config.add_defaults()
        # This connection belongs to the main thread, which only waits from now on and would never close it
        connections.close_all()

        # One service for every task that changes a job status, so the Kafka producers are created once, and only the
        # scheduler sends the intermediate workload statuses.
        transitions = JobTransitionService(workload_mirror=WorkloadBackgroundMirror())
        # one breaker per dependency per region
        breakers = FleetsBreakers()
        submitter = FleetsJobSubmitter(transitions, breakers)
        canceller = FleetsJobCanceller(transitions, breakers)

        # Inside a loop the tasks run in order. Across loops there is no order, so a task that wants fresh data
        # reads what the database holds, which is at most one iteration of the other loop old.
        self.loops = [
            self.loop(
                "ray",
                # submit jobs, status change from QUEUED to PENDING/FAILED
                ScheduleRayJobs(self.kill_signal, self.metrics),
                UpdateRayJobsStatuses(self.kill_signal, self.metrics),
                FreeRayResources(self.kill_signal, self.metrics),
            ),
            self.loop(
                "fleets-schedule",
                ScheduleFleetsJobs(self.kill_signal, self.metrics, submitter),
                StopBlockedFleetsJobs(self.kill_signal, canceller),
                # keeps a scarce compute profile busy with filler jobs, which the other tasks leave alone
                BalanceFillerJobs(self.kill_signal, self.metrics, transitions, submitter, canceller),
            ),
            # alone, so a slow submit can never make it miss the PENDING and RUNNING states of a short job
            self.loop(
                "fleets-update",
                UpdateFleetsJobsStatuses(self.kill_signal, self.metrics, transitions, canceller),
            ),
            self.loop(
                "maintenance",
                UpdateJobStatusCounts(self.kill_signal, self.metrics),
                ConsumeBlockedAccountEvents(self.kill_signal, self.metrics),
                OutboxTask(self.kill_signal, self.metrics),
                FreeFleetsResources(self.kill_signal, self.metrics, breakers),
                # last, so the gauge shows the cleanup breaker as this iteration left it. The submit and cancel
                # breakers are fed by other loops, so the gauge can be one iteration of those loops behind
                ExportFleetsBreakers(self.metrics, breakers),
            ),
        ]

    def loop(self, name: str, *tasks: SchedulerTask) -> SchedulerLoop:
        """A loop that runs these tasks in order, with what every loop shares."""
        return SchedulerLoop(name, list(tasks), self.kill_signal, self.metrics, self.health)

    @property
    def tasks(self) -> list:
        """Every task of every loop."""
        return [task for loop in self.loops for task in loop.tasks]

    def start_http_server(self):
        """Start the internal HTTP server for probes and metrics."""
        if self.http_server.is_running():
            raise RuntimeError("Scheduler HTTP server already running!")
        self.http_server.start()

    def stop_http_server(self):
        """Stop internal HTTP server"""
        self.http_server.stop()

    def close_tasks(self):
        """Close every task, each on its own, so one that fails to close does not keep the others open."""
        for task in self.tasks:
            try:
                task.close()
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.exception("Error closing %s: %s", task.name, ex)

    def run(self):
        """Run the loops, each in its own thread, until the kill signal is received or a loop dies."""
        logger.info("Scheduler started with the loops: %s", ", ".join(loop.name for loop in self.loops))
        # The scheduler's threads share this pool to hand slow calls to background threads
        get_background_executor().init()
        try:
            for loop in self.loops:
                loop.start()
            self.wait_for_the_end()
        finally:
            dead_loops = self.end_process()

        if dead_loops:
            # raised after the cleanup, not inside it, so it cannot hide an error that was already on its way out.
            # A non-zero exit makes docker or Kubernetes restart the process
            raise RuntimeError(f"Scheduler loops died: {', '.join(dead_loops)}")
        logger.info("Scheduler finished")

    def wait_for_the_end(self) -> None:
        """Wait on the main thread, which is the one Python delivers the signals to, until a stop is requested or a
        loop dies: a dead loop is not coming back, and the others would run on without it."""
        while not self.kill_signal.wait(1):
            if self.dead_loops():
                return

    def dead_loops(self) -> list[str]:
        """The names of the loops whose thread ended without a stop being requested."""
        if self.kill_signal.received:
            return []
        return [loop.name for loop in self.loops if not loop.is_alive()]

    def end_process(self) -> list[str]:
        """Stop and release everything, in order. Returns the names of the loops that died before the stop."""
        dead_loops = self.dead_loops()
        if dead_loops:
            logger.error("Scheduler loops %s are not running, stopping the scheduler", dead_loops)
        self.kill_signal.received = True
        self.join_loops()
        try:
            # after the loops, so running background tasks finish while the clients they use are still open
            get_background_executor().shutdown()
        finally:
            try:
                self.close_tasks()
            finally:
                try:
                    self.stop_http_server()
                finally:
                    connections.close_all()
        return dead_loops

    def join_loops(self):
        """Wait for every loop thread to finish its iteration, each on its own."""
        for loop in self.loops:
            try:
                loop.join()
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.exception("Error waiting for loop %s: %s", loop.name, ex)
