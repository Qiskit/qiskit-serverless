"""The status of the fleets of each Code Engine project, read in the background for the fleet cleanup."""

import logging
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone
from typing import Callable

from core.ibm_cloud.code_engine.fleets.handler import FleetHandler
from core.models import Job
from core.services.background_executor import BackgroundPool, get_background_executor
from core.services.runners import RunnerError, RunnerRetryableError

from scheduler.schedule import FleetsFleetDeleter

logger = logging.getLogger("scheduler.FleetCache")

LIST_EVERY_SECONDS = 300
LIST_MAX_AGE_SECONDS = 600
LIST_DEADLINE_SECONDS = 15
CHECK_EVERY_SECONDS = 30
STUCK_AFTER_SECONDS = 900
DELETING = "deleting"
DELETED = "deleted"
FOUND = "found"
FOUND_DELETED = "found_deleted"

POOL = BackgroundPool.CODE_ENGINE


@dataclass
class _Fleet:
    """One fleet as Code Engine last showed it, and why we deleted it, when we did."""

    status: str
    seen_at: float
    reason: str = FOUND_DELETED
    job_id: str | None = None
    deleting_since: float | None = None
    warned: bool = False


@dataclass
class _Project:  # pylint: disable=too-many-instance-attributes
    """What the cache knows about one project. The background tasks write ``fleets`` and ``listed_at``."""

    handler: FleetHandler | None = None
    region: str | None = None
    next_list_at: float = 0.0
    list_task: Future | None = None
    fleets: dict[str, _Fleet] = field(default_factory=dict)
    listed_at: float | None = None
    listed_at_wall: datetime | None = None
    scanned_at: float | None = None
    checking: set[str] = field(default_factory=set)


def _submit_to_pool(fn: Callable, *args, replace_key: str | None = None) -> Future | None:
    return get_background_executor().submit(POOL, fn, *args, replace_key=replace_key)


def _pool_has_room() -> bool:
    return get_background_executor().would_accept(POOL)


class FleetCache:
    """Keeps each project's fleet statuses fresh with lists and GETs in the background executor.

    A GET that finds a fleet deleted stamps ``fleet_deleted_at`` itself, so the scheduler never waits for a task.
    """

    def __init__(
        self,
        deleter: FleetsFleetDeleter,
        submit: Callable[..., Future | None] = _submit_to_pool,
        has_room: Callable[[], bool] = _pool_has_room,
        clock: Callable[[], float] = time.monotonic,
        on_deleted: Callable[[str], None] = lambda project: None,
    ):
        self.deleter = deleter
        self._on_deleted = on_deleted
        self._submit = submit
        self._has_room = has_room
        self._clock = clock
        self._lock = threading.Lock()
        self._projects: dict[str, _Project] = {}

    def refresh(self, projects: list[str]) -> None:
        """Submit the lists that are due, the GETs of the deleting fleets, then the GETs of the stale rows."""
        now = self._clock()
        ready = list(self._ready(projects, now))
        for name, project in ready:
            if now >= project.next_list_at and not _running(project.list_task):
                project.next_list_at = now + LIST_EVERY_SECONDS
                project.list_task = self._submit(self._list, project, now)
        for name, project in ready:
            self._submit_deleting_checks(name, project, now)
        for name, project in ready:
            self._submit_stale_checks(name, project)

    def listed(self, name: str) -> bool:
        """Whether the project has a list from the last LIST_MAX_AGE_SECONDS."""
        project = self._projects.get(name)
        return (
            project is not None
            and project.listed_at is not None
            and (self._clock() - project.listed_at <= LIST_MAX_AGE_SECONDS)
        )

    def need(self, name: str, threshold: int, held: int) -> int:
        """How many fleets the cap still has to delete, so the ones staying fall under the threshold.

        The deleting fleets still use the quota but are on their way out, so they are not deleted again. Zero without
        a fresh list. ``held`` is the DB count, which bounds the new fleets, so a quiet project costs no query.
        """
        if not self.listed(name):
            return 0
        project = self._projects[name]
        with self._lock:
            fleets, listed_at = dict(project.fleets), project.listed_at_wall
        staying = sum(1 for fleet in fleets.values() if fleet.status not in (DELETING, DELETED))
        if staying + held < threshold:
            return 0
        new, _stale = Job.objects.missing_from_list(name, fleets.keys(), listed_at)
        return max(0, staying + new.count() - threshold + 1)

    def alive(self, name: str) -> set[str]:
        """The fleet ids the cache shows alive in the project: listed, not deleting and not deleted."""
        project = self._projects.get(name)
        if project is None:
            return set()
        with self._lock:
            return {fleet_id for fleet_id, fleet in project.fleets.items() if fleet.status not in (DELETING, DELETED)}

    def deleting(self) -> set[str]:
        """Every fleet the cache shows deleting, in any project, so none gets a second DELETE."""
        with self._lock:
            return {
                fleet_id
                for project in self._projects.values()
                for fleet_id, fleet in project.fleets.items()
                if fleet.status == DELETING
            }

    def record_delete(self, name: str, job_id: str, fleet_id: str, reason: str) -> None:
        """Mark a fleet deleting from the moment Code Engine accepted its DELETE."""
        now = self._clock()
        project = self._projects.setdefault(name, _Project())
        with self._lock:
            project.fleets[fleet_id] = _Fleet(DELETING, now, reason, job_id, deleting_since=now)

    def _ready(self, projects: list[str], now: float):
        for name in projects:
            project = self._projects.setdefault(name, _Project())
            if self._ensure_handler(name, project, now) and not self.deleter.paused(project.region):
                yield name, project

    def _ensure_handler(self, name: str, project: _Project, now: float) -> bool:
        if project.handler is not None:
            return True
        if now < project.next_list_at:
            return False
        try:
            project.handler, project.region = self.deleter.handler(name)
        except RunnerError as ex:
            project.next_list_at = now + LIST_EVERY_SECONDS
            logger.error("project=%s cannot read its fleets in Code Engine: %s", name, ex)
            return False
        return True

    def _submit_deleting_checks(self, name: str, project: _Project, now: float) -> None:
        with self._lock:
            due = sorted(
                (fleet.seen_at, fleet_id)
                for fleet_id, fleet in project.fleets.items()
                if fleet.status == DELETING and now - fleet.seen_at >= CHECK_EVERY_SECONDS
            )
            stuck = [
                fleet
                for fleet in project.fleets.values()
                if fleet.status == DELETING
                and not fleet.warned
                and fleet.deleting_since is not None
                and now - fleet.deleting_since >= STUCK_AFTER_SECONDS
            ]
            for fleet in stuck:
                fleet.warned = True
        for fleet in stuck:
            logger.warning("job_id=%s still deleting in Code Engine after %ss", fleet.job_id, STUCK_AFTER_SECONDS)
        for _seen_at, fleet_id in due:
            if not self._submit_check(name, project, fleet_id):
                return

    def _submit_stale_checks(self, name: str, project: _Project) -> None:
        """Once per list, one GET per held terminal row the list does not show, terminal before the list started."""
        with self._lock:
            listed_at, listed_at_wall, known = project.listed_at, project.listed_at_wall, set(project.fleets)
        if listed_at is None or project.scanned_at == listed_at:
            return
        project.scanned_at = listed_at
        _new, stale = Job.objects.missing_from_list(name, known, listed_at_wall)
        for job_id, fleet_id in stale.values_list("id", "fleet_id"):
            if not self._submit_check(name, project, fleet_id, str(job_id)):
                return

    def _submit_check(self, name: str, project: _Project, fleet_id: str, job_id: str | None = None) -> bool:
        with self._lock:
            if fleet_id in project.checking:
                return True
            project.checking.add(fleet_id)
        if (
            self._has_room()
            and self._submit(self._check, name, project, fleet_id, job_id, replace_key=fleet_id) is not None
        ):
            return True
        with self._lock:
            project.checking.discard(fleet_id)
        return False

    def _list(self, project: _Project, started_at: float) -> None:
        started_at_wall = datetime.now(dt_timezone.utc)
        try:
            statuses = self.deleter.list_fleets(project.handler, project.region, started_at + LIST_DEADLINE_SECONDS)
        except RunnerRetryableError as ex:
            project.next_list_at = 0.0
            logger.warning("project_id=%s fleet list failed, trying again: %s", project.handler.project_id, ex)
            return
        except RunnerError as ex:
            logger.error("project_id=%s fleet list refused: %s", project.handler.project_id, ex)
            return
        with self._lock:
            fresh = {}
            for fleet_id, status in statuses.items():
                old = project.fleets.get(fleet_id)
                if old is not None and old.seen_at >= started_at:
                    fresh[fleet_id] = old
                elif old is not None:
                    # a fleet we deleted stays deleting until a GET or the list proves it deleted
                    status = DELETING if old.deleting_since is not None else status
                    fresh[fleet_id] = _Fleet(status, started_at, old.reason, old.job_id, old.deleting_since, old.warned)
                else:
                    fresh[fleet_id] = _Fleet(status, started_at)
            for fleet_id, old in project.fleets.items():
                if fleet_id not in fresh and old.seen_at >= started_at:
                    fresh[fleet_id] = old
            project.fleets = fresh
            project.listed_at, project.listed_at_wall = started_at, started_at_wall
        logger.info(
            "project_id=%s Code Engine lists %s fleets, %s of them deleting",
            project.handler.project_id,
            len(statuses),
            sum(1 for status in statuses.values() if status == DELETING),
        )

    def _check(self, name: str, project: _Project, fleet_id: str, job_id: str | None) -> None:
        checked_at = self._clock()
        try:
            exists = self.deleter.fleet_exists(project.handler, project.region, fleet_id)
        except RunnerError as ex:
            logger.warning("fleet_id=%s could not be checked in Code Engine: %s", fleet_id, ex)
            with self._lock:
                project.checking.discard(fleet_id)
            return
        with self._lock:
            project.checking.discard(fleet_id)
            fleet = project.fleets.get(fleet_id)
            reason = fleet.reason if fleet is not None else FOUND_DELETED
            job_id = job_id or (fleet.job_id if fleet is not None else None)
            if exists and fleet is not None:
                fleet.seen_at = checked_at
            elif exists:
                project.fleets[fleet_id] = _Fleet(FOUND, checked_at, reason, job_id)
            else:
                project.fleets[fleet_id] = _Fleet(DELETED, checked_at, reason, job_id)
        if not exists and job_id is not None and Job.objects.stamp_fleet_deleted(job_id, fleet_id, reason):
            self._on_deleted(name)


def _running(task: Future | None) -> bool:
    return task is not None and not task.done()
