"""Scheduler task that deletes the fleets of terminal jobs."""

import logging
import time
from datetime import timedelta

from django.db.models import Count, Q, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job
from core.services.runners import RunnerRetryableError

from scheduler.health import DB_EXCEPTIONS
from scheduler.kill_signal import KillSignal
from scheduler.metrics.scheduler_metrics_collector import SchedulerMetrics
from scheduler.schedule import FleetsBreakers, FleetsFleetDeleter
from .task import SchedulerTask

logger = logging.getLogger("scheduler.FreeFleetsResources")

DEFAULT_BUDGET_MS = 500
DEFAULT_MAX_DELETES_PER_CYCLE = 20
MAX_ATTEMPTS_PER_FLEET = 3
MAX_TRACKED_FAILURES = 500
DEFAULT_RETENTION_HOURS = 336
DEFAULT_QUOTA_PER_PROJECT = 1000
DEFAULT_FORCE_AT_PERCENT = 80
UNASSIGNED_PROJECT = "unassigned"


class FreeFleetsResources(SchedulerTask):
    """Delete the fleet of a terminal Fleets job, past the retention window or over the project's quota."""

    def __init__(
        self,
        kill_signal: KillSignal,
        metrics: SchedulerMetrics,
        breakers: FleetsBreakers | None = None,
    ):
        self.kill_signal = kill_signal
        self.metrics = metrics
        self.deleter = FleetsFleetDeleter(breakers or FleetsBreakers())
        self._failed_attempts: dict[str, int] = {}

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
        candidates = self._jobs_to_clean(self._projects_over_quota(counts), self.deleter.paused_regions())

        # a delete costs a Code Engine round trip and the loop is single threaded, so the batch is
        # bounded by time as well as by count. The budget starts here so it measures only the
        # deletes, and the first one always goes, or a slow cycle would never make progress.
        deadline = (
            time.monotonic() + Config.get_int(ConfigKey.FLEETS_CLEANUP_BUDGET_MS, default=DEFAULT_BUDGET_MS) / 1000
        )
        for position, job in enumerate(candidates):
            if self.kill_signal.received or (position and time.monotonic() >= deadline):
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

        # only a True proves Code Engine answered: a False may never have reached it
        for region in answered_regions - failed_regions:
            self.deleter.record_cycle(region, code_engine_answered=True)

    def _jobs_to_clean(self, over_quota: dict[str, int], paused_regions: list[str | None]) -> list[Job]:
        """The jobs this cycle may delete: the projects over their quota first, then the retention window.

        A project over its quota takes only the fleets it needs to get back under the threshold, and a
        paused region is excluded here so its backlog cannot fill the batch.
        """
        budget = Config.get_int(ConfigKey.FLEETS_CLEANUP_MAX_DELETES, default=DEFAULT_MAX_DELETES_PER_CYCLE)
        deletable = (
            Job.objects.held_fleets()
            .filter(status__in=Job.TERMINAL_STATUSES)
            .with_fleet_region()
            .exclude(self._in_regions(paused_regions))
            .exclude(id__in=self._giving_up_on())
        )

        jobs: list[Job] = []
        for project, needed in over_quota.items():
            if len(jobs) >= budget:
                break
            take = min(needed, budget - len(jobs))
            jobs += list(deletable.filter(ce_project_name=project).order_by("updated")[:take])

        if len(jobs) < budget:
            jobs += list(
                self._past_the_window(deletable).exclude(id__in=[job.id for job in jobs])[: budget - len(jobs)]
            )
        return jobs

    @staticmethod
    def _past_the_window(deletable):
        """The jobs whose retention window has passed, oldest first, measured on ``updated``."""
        retention = max(1, Config.get_int(ConfigKey.FLEETS_CLEANUP_RETENTION_HOURS, default=DEFAULT_RETENTION_HOURS))
        cutoff = timezone.now() - timedelta(hours=retention)
        return deletable.filter(updated__lt=cutoff).order_by("updated")

    @staticmethod
    def _in_regions(regions: list[str | None]) -> Q:
        """Match the jobs of these regions, by the same region ``Job.fleet_region`` reports.

        A null region needs its own clause, `IN` never matches it.
        """
        named = [region for region in regions if region is not None]
        matched = Q(fleet_region_sql__in=named) if named else Q(pk__in=[])
        if None in regions:
            matched |= Q(fleet_region_sql__isnull=True)
        return matched

    def _projects_over_quota(self, counts: dict[str, int]) -> dict[str, int]:
        """How many fleets each project over its quota has to lose to get back under the threshold."""
        percent = Config.get_int(ConfigKey.FLEETS_CLEANUP_FORCE_AT_PERCENT, default=DEFAULT_FORCE_AT_PERCENT)
        quota = Config.get_int(ConfigKey.FLEETS_QUOTA_PER_PROJECT, default=DEFAULT_QUOTA_PER_PROJECT)
        if not 1 <= percent < 100 or quota < 1:
            return {}

        threshold = quota * percent // 100
        return {
            project: held - threshold + 1
            for project, held in counts.items()
            if project != UNASSIGNED_PROJECT and held >= threshold
        }

    def _giving_up_on(self) -> list[str]:
        """Job ids that failed MAX_ATTEMPTS_PER_FLEET times, so one bad row cannot fill the batch."""
        return [job_id for job_id, failures in self._failed_attempts.items() if failures >= MAX_ATTEMPTS_PER_FLEET]

    def _delete_and_stamp(self, job: Job) -> bool:
        """Delete one job's fleet and stamp it. A failure is counted so a bad row is skipped later."""
        if self.deleter.delete(job):
            job.update_fields({"fleet_deleted_at": timezone.now()})
            self._failed_attempts.pop(str(job.id), None)
            return True

        self._count_failure(job)
        return False

    def _count_failure(self, job: Job) -> None:
        """Count one failed attempt on a job, and log it, at ERROR once it reached the limit."""
        while len(self._failed_attempts) >= MAX_TRACKED_FAILURES:
            self._failed_attempts.pop(next(iter(self._failed_attempts)))
        failures = self._failed_attempts.get(str(job.id), 0) + 1
        self._failed_attempts[str(job.id)] = failures
        logger.log(
            logging.ERROR if failures >= MAX_ATTEMPTS_PER_FLEET else logging.WARNING,
            "job_id=%s fleet_id=%s not deleted on attempt %s, it still holds a slot in its project",
            job.id,
            job.fleet_id,
            failures,
        )

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
