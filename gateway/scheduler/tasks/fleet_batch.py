"""Picks the fleets one cleanup cycle should delete."""

import logging
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.config_key import ConfigKey
from core.models import Config, Job

logger = logging.getLogger("scheduler.FleetBatch")

DEFAULT_MAX_DELETES_PER_CYCLE = 20
MAX_ATTEMPTS_PER_FLEET = 3
MAX_TRACKED_FAILURES = 500
DEFAULT_RETENTION_HOURS = 336
DEFAULT_QUOTA_PER_PROJECT = 1000
DEFAULT_FORCE_AT_PERCENT = 80
# Jobs with no ce_project_name cannot be counted against a project
UNASSIGNED_PROJECT = "unassigned"


class FleetBatch:
    """The fleets a cycle should delete, and the memory of the ones that keep failing.

    One instance per process: the attempt counts are what let the batch get past a fleet Code Engine
    will never delete, so rebuilding it every cycle would reset them and the same row would refill
    every batch.
    """

    def __init__(self) -> None:
        self._failed_attempts: dict[str, int] = {}

    def next_batch(self, counts: dict[str, int], paused_regions: list[str | None]) -> list[Job]:
        """The jobs this cycle may delete: the projects over their quota first, then the retention window.

        A project over its quota takes only the fleets it needs to get back under the threshold, so a
        cycle cannot destroy fleets that are still inside their window beyond what the cap asked for.
        Urgent goes first because its fleets are the newest, so a shared ordering would always put the
        routine backlog ahead of it. Paused regions are excluded in the query rather than in the
        caller's loop, or their backlog would fill the batch and no other region would be cleaned up.
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
        for project, needed in self._projects_over_quota(counts).items():
            if len(jobs) >= budget:
                break
            take = min(needed, budget - len(jobs))
            jobs += list(deletable.filter(ce_project_name=project).order_by("finished_at")[:take])

        if len(jobs) < budget:
            jobs += list(
                self._past_the_window(deletable).exclude(id__in=[job.id for job in jobs])[: budget - len(jobs)]
            )
        return jobs

    def count_failure(self, job: Job) -> None:
        """Count one failed attempt on a job, and log the one that reached the limit."""
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

    def forget(self, job: Job) -> None:
        """Drop a job's attempt count, once its fleet is gone."""
        self._failed_attempts.pop(str(job.id), None)

    @staticmethod
    def _past_the_window(deletable):
        """The jobs whose retention window has passed, oldest first.

        The window measures ``finished_at``, not ``updated``: stamping the delete writes ``updated``,
        so a window keyed on it would move every time the cleanup touched the row.
        """
        retention = max(1, Config.get_int(ConfigKey.FLEETS_CLEANUP_RETENTION_HOURS, default=DEFAULT_RETENTION_HOURS))
        cutoff = timezone.now() - timedelta(hours=retention)
        return deletable.filter(finished_at__lt=cutoff).order_by("finished_at")

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

    @staticmethod
    def _projects_over_quota(counts: dict[str, int]) -> dict[str, int]:
        """How many fleets each project over its quota has to lose to get back under the threshold."""
        percent = Config.get_int(ConfigKey.FLEETS_CLEANUP_FORCE_AT_PERCENT, default=DEFAULT_FORCE_AT_PERCENT)
        quota = Config.get_int(ConfigKey.FLEETS_QUOTA_PER_PROJECT, default=DEFAULT_QUOTA_PER_PROJECT)
        # either at 0 or below floors the threshold to 0, which puts every project over quota
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
