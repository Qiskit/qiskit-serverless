"""Free the Code Engine fleet of a terminal job."""

import logging
from datetime import timedelta

from django.db.models import Count, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job
from core.services.runners import RunnerUnavailableError

from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import delete_fleet, deletes_paused, record_delete_batch
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeFleetsResources")

MAX_DELETES_PER_CYCLE = 20
# Counted in scheduler loops, which are about a second each
REPORT_EVERY_LOOPS = 300


class FreeFleetsResources(SchedulerTask):
    """Delete the fleet of a terminal Fleets job once the retention window has passed."""

    def __init__(self, kill_signal: KillSignal, metrics: SchedulerMetrics):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self._report_loops = 0

    def run(self):
        """Delete the fleets past the retention window, and report the fleets we hold."""
        self._report_held_fleets()

        if not Config.get_bool(ConfigKey.FLEETS_CLEANUP_ENABLED):
            return
        if deletes_paused():
            return

        attempted = succeeded = False
        for job in self._jobs_to_clean():
            if self.kill_signal.received:
                return
            attempted = True
            try:
                succeeded |= self._delete_and_stamp(job)
            except RunnerUnavailableError as ex:
                logger.warning("Code Engine is unavailable, stopping this cleanup cycle: %s", ex)
                return
        record_delete_batch(attempted=attempted, succeeded=succeeded)

    def _jobs_to_clean(self):
        """Terminal Fleets jobs whose fleet is older than the retention window, oldest first."""
        retention = Config.get_int(ConfigKey.FLEETS_CLEANUP_RETENTION_HOURS)
        return (
            Job.objects.held_fleets()
            .filter(status__in=Job.TERMINAL_STATUSES, updated__lt=timezone.now() - timedelta(hours=retention))
            .order_by("updated")[:MAX_DELETES_PER_CYCLE]
        )

    def _delete_and_stamp(self, job: Job) -> bool:
        """Delete one job's fleet and stamp it. Returns False when the delete could not be sent."""
        if not delete_fleet(job):
            logger.warning("job_id=%s fleet_id=%s not deleted, retrying later", job.id, job.fleet_id)
            return False

        job.update_fields({"fleet_deleted_at": timezone.now()})
        logger.info("job_id=%s fleet_id=%s deleted", job.id, job.fleet_id)
        return True

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
