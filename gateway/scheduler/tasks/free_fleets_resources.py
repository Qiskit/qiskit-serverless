"""Scheduler task that deletes the fleets of terminal jobs."""

import logging
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
from scheduler.tasks.task import SchedulerTask

logger = logging.getLogger("scheduler.FreeFleetsResources")

DEFAULT_MAX_DELETES_PER_CYCLE = 20
MAX_ATTEMPTS_PER_FLEET = 3
MAX_TRACKED_FAILURES = 500
DEFAULT_RETENTION_HOURS = 336
DEFAULT_QUOTA_PER_PROJECT = 1000
DEFAULT_FORCE_AT_PERCENT = 80
# Jobs with no ce_project_name cannot be counted against a project
UNASSIGNED_PROJECT = "unassigned"


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
        self._failed_attempts: dict[str, int] = {}
        self._wedged_projects: set[str] = set()

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
        for job in candidates:
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

    def _jobs_to_clean(self, over_quota: dict[str, int], paused_regions: list[str | None]) -> list[Job]:
        """The jobs this cycle may delete: the projects over their quota first, then the retention window.

        A project over its quota takes only the fleets it needs to get back under the threshold, so a
        cycle cannot destroy fleets that are still inside their window beyond what the cap asked for.
        Urgent goes first because its fleets are the newest, so a shared ordering would always put the
        routine backlog ahead of it.
        """
        budget = Config.get_int(ConfigKey.FLEETS_CLEANUP_MAX_DELETES, default=DEFAULT_MAX_DELETES_PER_CYCLE)
        deletable = (
            Job.objects.held_fleets()
            .filter(status__in=Job.TERMINAL_STATUSES)
            .exclude(self._in_regions(paused_regions))
            .exclude(id__in=self._giving_up_on())
        )

        jobs: list[Job] = []
        for project, needed in over_quota.items():
            if len(jobs) >= budget:
                break
            take = min(needed, budget - len(jobs))
            jobs += list(deletable.filter(ce_project_name=project).order_by("finished_at")[:take])

        if len(jobs) < budget:
            jobs += list(
                self._past_the_window(deletable).exclude(id__in=[job.id for job in jobs])[: budget - len(jobs)]
            )
        return jobs

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
        """Match the jobs of these regions. A null region needs its own clause, `IN` never matches it."""
        named = [region for region in regions if region is not None]
        matched = Q(ce_region__in=named) if named else Q(pk__in=[])
        if None in regions:
            matched |= Q(ce_region__isnull=True)
        return matched

    def _projects_over_quota(self, counts: dict[str, int]) -> dict[str, int]:
        """How many fleets each project over its quota has to lose to get back under the threshold."""
        percent = Config.get_int(ConfigKey.FLEETS_CLEANUP_FORCE_AT_PERCENT, default=DEFAULT_FORCE_AT_PERCENT)
        # 0 or a negative would floor the threshold to 0, making every project over quota
        if not 1 <= percent < 100:
            return {}

        quota = Config.get_int(ConfigKey.FLEETS_QUOTA_PER_PROJECT, default=DEFAULT_QUOTA_PER_PROJECT)
        threshold = quota * percent // 100
        over = {
            project: held - threshold + 1
            for project, held in counts.items()
            if project != UNASSIGNED_PROJECT and held >= threshold
        }
        for project, _ in over.items():
            self._report_wedged(project, held=counts[project], quota=quota)
        self._wedged_projects &= set(over)
        return over

    def _report_wedged(self, project: str, *, held: int, quota: int) -> None:
        """Log a project that is over its quota with nothing it may delete, once per spell."""
        if self._deletable_in(project):
            self._wedged_projects.discard(project)
            return
        if project in self._wedged_projects:
            return
        self._wedged_projects.add(project)
        logger.error(
            "project=%s holds %s of %s fleets and none of them belongs to a terminal job, so no slot can be freed",
            project,
            held,
            quota,
        )

    def _deletable_in(self, project: str) -> bool:
        """Whether a project over its quota has any fleet we are allowed to delete."""
        return (
            Job.objects.held_fleets()
            .filter(status__in=Job.TERMINAL_STATUSES, ce_project_name=project)
            .exclude(id__in=self._giving_up_on())
            .exists()
        )

    def _giving_up_on(self) -> list[str]:
        """Job ids that failed MAX_ATTEMPTS_PER_FLEET times, so one bad row cannot fill the batch."""
        return [job_id for job_id, failures in self._failed_attempts.items() if failures >= MAX_ATTEMPTS_PER_FLEET]

    def _delete_and_stamp(self, job: Job) -> bool:
        """Delete one job's fleet and stamp it. A failure is counted so a bad row is skipped later."""
        if self.deleter.delete(job):
            job.update_fields({"fleet_deleted_at": timezone.now()})
            self._failed_attempts.pop(str(job.id), None)
            logger.info("job_id=%s fleet_id=%s deleted", job.id, job.fleet_id)
            return True

        self._count_failure(job)
        return False

    def _count_failure(self, job: Job) -> None:
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
