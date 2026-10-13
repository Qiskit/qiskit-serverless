"""Scheduler task that deletes the fleets of terminal jobs."""

import logging

from django.db.models import Count, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job
from core.services.runners import RunnerRetryableError

from scheduler.health import DB_EXCEPTIONS
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import FleetsBreakers, FleetsFleetDeleter
from scheduler.tasks.fleet_batch import UNASSIGNED_PROJECT, FleetBatch
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeFleetsResources")


class FreeFleetsResources(SchedulerTask):
    """Delete the fleet of a terminal Fleets job once the retention window has passed."""

    def __init__(
        self,
        kill_signal: KillSignal,
        metrics: SchedulerMetrics,
        breakers: FleetsBreakers | None = None,
    ):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.deleter = FleetsFleetDeleter(breakers or FleetsBreakers())
        # one per process: the batch remembers the fleets that keep failing
        self.batch = FleetBatch()

    def run(self):
        """Delete the fleets past the retention window or over their project's quota, and report what we hold."""
        counts: dict[str, int] = {}
        try:
            counts = self._count_held_fleets()
        except DB_EXCEPTIONS:
            raise
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.error("Could not count the held fleets: %s", ex)

        if not Config.get_bool(ConfigKey.FLEETS_CLEANUP_ENABLED):
            return

        failed_regions: set[str | None] = set()
        answered_regions: set[str | None] = set()
        for job in self.batch.next_batch(counts, self.deleter.paused_regions()):
            if self.kill_signal.received:
                break
            region = job.fleet_region
            if region in failed_regions:
                continue

            try:
                if self._delete_and_stamp(job):
                    answered_regions.add(region)
            except RunnerRetryableError as ex:
                logger.warning("job_id=%s region=%s fleet not deleted: %s", job.id, region, ex)
                self.deleter.record_cycle(region, code_engine_answered=False)
                failed_regions.add(region)

        # only a delete that came back True proves Code Engine answered: a False can be a missing
        # project row or a host that does not resolve, neither of which reached it
        for region in answered_regions - failed_regions:
            self.deleter.record_cycle(region, code_engine_answered=True)

    def _delete_and_stamp(self, job: Job) -> bool:
        """Delete one job's fleet and stamp it. A failure is counted so a bad row is skipped later."""
        if self.deleter.delete(job):
            job.update_fields({"fleet_deleted_at": timezone.now()})
            self.batch.forget(job)
            logger.info("job_id=%s fleet_id=%s deleted", job.id, job.fleet_id)
            return True

        self.batch.count_failure(job)
        return False

    def _count_held_fleets(self) -> dict[str, int]:
        """Count the fleets we hold per project, whatever the job status, and report them."""
        counts = {
            row["ce_project"]: row["total"]
            for row in (
                Job.objects.held_fleets()
                .annotate(ce_project=Coalesce(NullIf("ce_project_name", Value("")), Value(UNASSIGNED_PROJECT)))
                .values("ce_project")
                .annotate(total=Count("id"))
            )
        }
        try:
            self.metrics.clear_held_fleets()
            for project, total in counts.items():
                self.metrics.set_held_fleets(total, project)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            logger.error("Could not report the held fleets: %s", ex)
        return counts
