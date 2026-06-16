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

"""Shared helpers and constants for fleets integration tests.

Imports belong here (not in conftest.py) so test modules don't violate the
pytest idiom of treating conftest as fixtures-only.
"""

import time
import uuid

from botocore.exceptions import ClientError

CLIENT_TO_DB_STATUS = {
    "QUEUED": "QUEUED",
    "INITIALIZING": "PENDING",
    "RUNNING": "RUNNING",
    "DONE": "SUCCEEDED",
    "ERROR": "FAILED",
    "CANCELED": "STOPPED",
}

VALID_DB_STATUS_ORDER = ["QUEUED", "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "STOPPED"]

FLEET_STATE_BUCKETS = ["fleet-state", "fleet-state-archive", "task-store-bucket"]
DATA_BUCKETS = ["user-data-bucket", "provider-data-bucket"]


def is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string.

    Args:
        value: The string to validate.

    Returns:
        True if the string is a valid UUID, False otherwise.
    """
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def wait_for_terminal(job, timeout=120):
    """Poll job.status() until a terminal state is reached.

    Args:
        job: A ServerlessJob instance.
        timeout: Maximum seconds to wait.

    Returns:
        A tuple of (job_id, client_status) where client_status is one of
        DONE, ERROR, or CANCELED.

    Raises:
        AssertionError: If the job does not reach a terminal state within timeout.
    """
    job_id = job.job_id
    deadline = time.time() + timeout
    client_status = None
    while time.time() < deadline:
        client_status = job.status()
        if client_status in ("DONE", "ERROR", "CANCELED"):
            return job_id, client_status
        time.sleep(2)
    raise AssertionError(f"Job {job_id} did not reach terminal state within {timeout}s, last status: {client_status}")


def wait_for_s3_object(minio_client, bucket, key, timeout=30):
    """Retry until an S3 object exists, or raise after timeout.

    Args:
        minio_client: A boto3 S3 client.
        bucket: The bucket name to look in.
        key: The object key to wait for.
        timeout: Maximum seconds to wait before raising.

    Returns:
        The S3 GetObject response dict.

    Raises:
        AssertionError: If the object is not found within the timeout.
    """
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            obj = minio_client.get_object(Bucket=bucket, Key=key)
            return obj
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                last_err = e
                time.sleep(1)
            else:
                raise
    raise AssertionError(f"S3 object s3://{bucket}/{key} not found after {timeout}s") from last_err


def wait_for_db_condition(pg_conn, query, params, predicate, timeout=30):
    """Retry a DB query until predicate(row) is True, or raise after timeout.

    Args:
        pg_conn: A psycopg2 connection with autocommit enabled.
        query: SQL query string (should return a single row).
        params: Query parameters tuple.
        predicate: Callable that receives the fetched row and returns bool.
        timeout: Maximum seconds to wait before raising.

    Returns:
        The first row for which predicate returns True.

    Raises:
        AssertionError: If the condition is not met within the timeout.
    """
    deadline = time.time() + timeout
    last_row = None
    while time.time() < deadline:
        cur = pg_conn.cursor()
        cur.execute(query, params)
        last_row = cur.fetchone()
        cur.close()
        if last_row is not None and predicate(last_row):
            return last_row
        time.sleep(1)
    raise AssertionError(f"DB condition not met after {timeout}s. Last row: {last_row}")
