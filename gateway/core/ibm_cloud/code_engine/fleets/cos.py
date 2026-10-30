# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""COS operations for fleet job artifacts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple

import yaml

from core.ibm_cloud.cos.cos_client import COSClient

logger = logging.getLogger("FleetHandler")

# The task file holds the environment of the task, tokens included, so it is never read past this size.
# The real one is about 3 KiB.
TASK_FILE_MAX_BYTES = 256 * 1024

# How far ahead of the gateway clock a time from Code Engine may read before it is discarded. The two clocks are not
# synchronized, so a time that has just happened can read as a moment that has not happened here yet.
TASK_TIME_CLOCK_SKEW = timedelta(minutes=1)


# Task-store schema versions, newest first. Code Engine writes the task state under a
# version segment and only these two exist: v3 is the layout it is moving to, v2 the
# layout of fleets created before the switch. Readers try them in this order.
#
# Cost, deliberately accepted: Code Engine still creates v2 fleets by default, so a
# reader pays one empty v3 listing per poll before v2 answers. That doubles the listing
# cost per running job for the transition, and it disappears on its own once Code Engine
# switches to v3, because the first probe then answers. Memoizing the version per fleet
# would remove it sooner at the price of process-wide mutable state.
TASK_STORE_VERSIONS = ("v3", "v2")


def queue_prefix(project_id: str, fleet_id: str, version: str = TASK_STORE_VERSIONS[0]) -> str:
    """Build the COS task-state queue key prefix for a fleet.

    Single source for the ``ce/{project_id}/{fleet_id}/{version}/queue/`` layout
    shared by the status reader (FleetsRunner) and the fleets mock, so they cannot
    drift. The fleet-worker test image is a separate container and keeps a
    documented mirror of this format.

    Args:
        project_id: The CE project UUID.
        fleet_id: The fleet UUID.
        version: Task-store schema version segment. Defaults to the newest.

    Returns:
        The queue key prefix, ending in a trailing slash.
    """
    return f"ce/{project_id}/{fleet_id}/{version}/queue/"


def task_state_from_key(prefix: str, key: str) -> str | None:
    """Return the task state a queue key encodes, or ``None``.

    The state is the first path segment after ``prefix``, whichever schema version
    ``prefix`` carries, so no caller has to parse the version. Everything deeper in
    the key (worker name, timestamps, task index, batch name) cannot be mistaken
    for the state, which matters because the batch name is user supplied.

    Args:
        prefix: Queue prefix the key was listed under, ending in ``queue/``.
        key: A COS object key.

    Returns:
        The lowercased state segment, or ``None`` when the key does not sit under
        ``prefix`` or carries no state, such as a directory marker.
    """
    if not key.startswith(prefix):
        return None
    return key[len(prefix) :].split("/", 1)[0].strip().lower() or None


def tasks_prefix(project_id: str, fleet_id: str, version: str = TASK_STORE_VERSIONS[0]) -> str:
    """Build the COS task file key prefix for a fleet.

    Code Engine keeps one file per task under ``ce/{project_id}/{fleet_id}/{version}/tasks/``, named after the task
    id. Unlike the keys under ``queue/``, it stays after the task ends, and it holds when the task started and
    finished. A job runs a single task, so the prefix holds a single file.

    Args:
        project_id: The CE project UUID.
        fleet_id: The fleet UUID.
        version: Task-store schema version segment. Defaults to the newest.

    Returns:
        The tasks key prefix, ending in a trailing slash.
    """
    return f"ce/{project_id}/{fleet_id}/{version}/tasks/"


class TaskTimes(NamedTuple):
    """When Code Engine says the task started and finished, each ``None`` while unknown."""

    started_at: datetime | None = None
    finished_at: datetime | None = None


def _aware_datetime(value: Any) -> datetime | None:
    """The value as an aware datetime, or ``None`` when it is not one. YAML reads an unquoted timestamp as a
    datetime and a quoted one as a string; both are accepted."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None
    return value


def parse_task_times(content: bytes, source: str) -> TaskTimes:
    """Read ``startedAt`` and ``finishedAt`` from the content of a task file.

    The ``startTime`` and ``endTime`` of the worker under ``status`` are not read. The file holds the environment
    of the task, tokens included, so nothing of its content is logged, not even in the error of a bad YAML.

    Args:
        content: The task file, YAML.
        source: Where it comes from, only used to log.

    Returns:
        The times found. A key that is missing, null, not a timestamp or without a timezone is ``None``.
    """
    try:
        document = yaml.safe_load(content)
    except (yaml.YAMLError, ValueError) as exc:
        # Not the message: a YAML error quotes the line it failed on. A ValueError is a timestamp YAML cannot build,
        # like year 0000
        logger.warning("Task file %s is not valid YAML (%s)", source, type(exc).__name__)
        return TaskTimes()
    if not isinstance(document, dict):
        logger.warning("Task file %s is not a YAML mapping", source)
        return TaskTimes()

    times = {}
    for field, key in (("started_at", "startedAt"), ("finished_at", "finishedAt")):
        raw = document.get(key)
        parsed = _aware_datetime(raw)
        if raw is not None and parsed is None:
            logger.warning("Task file %s has a %s that is not a timestamp with a timezone", source, key)
        times[field] = parsed
    return TaskTimes(**times)


def plausible_task_times(
    times: TaskTimes, created: datetime, running_started_at: datetime | None, source: str
) -> TaskTimes:
    """The times that can be true, each ``None`` otherwise, so callers get a time or nothing, never a made up one.

    A start cannot be before the job was created, and an end cannot be before the start (the one of the file, or else
    the one the job already has, or else the creation of the job). Neither can be ahead of now by more than
    ``TASK_TIME_CLOCK_SKEW``. Code Engine writes a zero time (year 1) in ``finishedAt`` while the task runs, which
    this discards. A time that is discarded does not discard the other.

    Args:
        times: What the task file says.
        created: When the job was created.
        running_started_at: The start the job already has, if any.
        source: Where the times come from, only used to log.
    """
    latest = datetime.now(timezone.utc) + TASK_TIME_CLOCK_SKEW

    def _within(name: str, value: datetime | None, earliest: datetime) -> datetime | None:
        if value is None or earliest <= value <= latest:
            return value
        logger.warning(
            "Task file %s has a %s of %s, out of the %s to %s it can be, ignoring it",
            source,
            name,
            value.isoformat(),
            earliest.isoformat(),
            latest.isoformat(),
        )
        return None

    started_at = _within("startedAt", times.started_at, created)
    return TaskTimes(started_at, _within("finishedAt", times.finished_at, started_at or running_started_at or created))


class JobCOS:
    """COS operations wrapper for fleet job artifacts."""

    def __init__(self, cos_client: COSClient) -> None:
        self._cos = cos_client

    def wait_for_object(
        self,
        *,
        bucket_name: str,
        key: str,
        timeout: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """Wait until an object exists in COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            timeout: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            ValueError: If bucket_name or key is missing.
            TimeoutError: If the object does not appear in time.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.wait_until_object_exists(
            bucket=bucket_name,
            key=key,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
        )

    def delete_object(
        self,
        *,
        bucket_name: str,
        key: str,
        wait: bool = True,
        timeout: int = 180,
        poll_interval: int = 2,
    ) -> None:
        """Delete an object from COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            wait: Whether to wait until deletion is confirmed.
            timeout: Maximum wait time in seconds.
            poll_interval: Poll interval in seconds.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.delete_object(
            bucket=bucket_name,
            key=key,
            wait=wait,
            timeout_seconds=timeout,
            poll_interval=poll_interval,
        )

    def upload_fileobj(
        self,
        *,
        fileobj: object,
        bucket_name: str,
        key: str,
    ) -> None:
        """Upload a file-like object to COS.

        Args:
            fileobj: Binary file-like object to upload.
            bucket_name: COS bucket name.
            key: Object key.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        self._cos.upload_fileobj(fileobj=fileobj, bucket=bucket_name, key=key)

    def get_object_bytes(self, *, bucket_name: str, key: str) -> bytes:
        """Retrieve an object fully into memory.

        Args:
            bucket_name: COS bucket name.
            key: Object key.

        Returns:
            Object content as bytes.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")

        return self._cos.get_object_bytes(bucket=bucket_name, key=key)

    def list_keys(
        self,
        *,
        bucket_name: str,
        prefix: str | None = None,
    ) -> list[str]:
        """List object keys in a COS bucket.

        Args:
            bucket_name: COS bucket name.
            prefix: Optional key prefix to filter results.

        Returns:
            List of object keys.
        """
        return self._cos.list_keys(bucket=bucket_name, prefix=prefix)

    def list_with_metadata(
        self,
        *,
        bucket_name: str,
        prefix: str,
    ) -> list[dict]:
        """List objects under a prefix with size and last_modified metadata.

        Args:
            bucket_name: COS bucket name.
            prefix: Key prefix to filter results.

        Returns:
            List of dicts with keys ``key``, ``size``, ``last_modified``.

        Raises:
            ValueError: If bucket_name is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        return self._cos.list_with_metadata(bucket=bucket_name, prefix=prefix)

    def head_object(self, *, bucket_name: str, key: str) -> None:
        """Check that an object exists in COS.

        Args:
            bucket_name: COS bucket name.
            key: Object key.

        Raises:
            ValueError: If bucket_name or key is missing.
            ClientError: If the object does not exist or an unexpected error occurs.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        self._cos.head_object(bucket=bucket_name, key=key)

    def get_presigned_url(self, *, bucket_name: str, key: str, expiry: int = 3600) -> str:
        """Generate a presigned GET URL for an object.

        Args:
            bucket_name: COS bucket name.
            key: Object key.
            expiry: URL validity in seconds (default 3600).

        Returns:
            Presigned URL string.

        Raises:
            ValueError: If bucket_name or key is missing.
        """
        if not bucket_name:
            raise ValueError("bucket_name is required.")
        if not key:
            raise ValueError("key is required.")
        return self._cos.generate_presigned_url(bucket=bucket_name, key=key, expiry=expiry)
