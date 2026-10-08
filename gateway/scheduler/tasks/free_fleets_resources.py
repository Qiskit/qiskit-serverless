"""Scheduler task that deletes the fleets of terminal jobs."""

import logging
from datetime import timedelta

from django.db.models import Count, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job
from core.services.runners import RunnerUnavailableError

from scheduler.health import DB_EXCEPTIONS
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import code_engine_paused, delete_fleet, record_delete_cycle
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeFleetsResources")

MAX_DELETES_PER_CYCLE = 20
# A fleet that keeps failing is skipped rather than stamped, so a bad row never leaves the gauge
MAX_ATTEMPTS_PER_FLEET = 3
# Caps the in-process state. Clearing it retries everything, which is what a restart does anyway.
MAX_TRACKED_FAILURES = 500
DEFAULT_RETENTION_HOURS = 48
# Counted in scheduler loops, which are about a second each
REPORT_EVERY_LOOPS = 300


class FreeFleetsResources(SchedulerTask):
    """Delete the fleet of a terminal Fleets job once the retention window has passed."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._report_loops = 0
        self._failed_attempts: dict[str, int] = {}

    def run(self):
        """Delete the fleets past the retention window, and report the fleets we hold."""
        try:
            self._report_held_fleets()
        except DB_EXCEPTIONS:
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.error("Could not report the held fleets: %s", ex)

        if not Config.get_bool(ConfigKey.FLEETS_CLEANUP_ENABLED):
            return
        if code_engine_paused():
            return

        attempted = False
        for job in self._jobs_to_clean():
            if self.kill_signal.received:
                return
            attempted = True
            try:
                self._delete_and_stamp(job)
            except RunnerUnavailableError as ex:
                logger.warning("Code Engine is unavailable, stopping this cleanup cycle: %s", ex)
                record_delete_cycle(code_engine_answered=False)
                return

        if attempted:
            record_delete_cycle(code_engine_answered=True)

    def _jobs_to_clean(self):
        """Terminal Fleets jobs whose last update is older than the retention window, oldest first."""
        retention = Config.get_int(ConfigKey.FLEETS_CLEANUP_RETENTION_HOURS, default=DEFAULT_RETENTION_HOURS)
        return (
            Job.objects.held_fleets()
            .filter(status__in=Job.TERMINAL_STATUSES, updated__lt=timezone.now() - timedelta(hours=retention))
            .exclude(id__in=self._giving_up_on())
            .order_by("updated")[:MAX_DELETES_PER_CYCLE]
        )

    def _giving_up_on(self) -> list[str]:
        """Job ids that failed MAX_ATTEMPTS_PER_FLEET times, so one bad row cannot fill the batch."""
        return [job_id for job_id, failures in self._failed_attempts.items() if failures >= MAX_ATTEMPTS_PER_FLEET]

    def _delete_and_stamp(self, job: Job) -> bool:
        """Delete one job's fleet and stamp it, counting a failure so a bad row is skipped later."""
        if delete_fleet(job):
            job.update_fields({"fleet_deleted_at": timezone.now()})
            self._failed_attempts.pop(str(job.id), None)
            logger.info("job_id=%s fleet_id=%s deleted", job.id, job.fleet_id)
            return True

        if len(self._failed_attempts) >= MAX_TRACKED_FAILURES:
            self._failed_attempts.clear()
        failures = self._failed_attempts.get(str(job.id), 0) + 1
        self._failed_attempts[str(job.id)] = failures
        logger.log(
            logging.ERROR if failures >= MAX_ATTEMPTS_PER_FLEET else logging.WARNING,
            "job_id=%s fleet_id=%s not deleted on attempt %s, it still holds a slot in its project",
            job.id,
            job.fleet_id,
            failures,
        )
        return False

    def _report_held_fleets(self):
        """Count the fleets we hold per project, whatever the job status, once every REPORT_EVERY_LOOPS."""
        if self._report_loops > 0:
            self._report_loops -= 1
            return
        self._report_loops = REPORT_EVERY_LOOPS

        counts = (
            Job.objects.held_fleets()
            .annotate(ce_project=Coalesce(NullIf("ce_project_name", Value("")), Value("unassigned")))
            .values("ce_project")
            .annotate(total=Count("id"))
        )
        self.metrics.clear_held_fleets()
        for row in counts:
            self.metrics.set_held_fleets(row["total"], row["ce_project"])
