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

import requests
from botocore.exceptions import ClientError
from qiskit_serverless.utils.http import get_headers

CLIENT_TO_DB_STATUS = {
    "QUEUED": "QUEUED",
    "INITIALIZING": "PENDING",
    "RUNNING": "RUNNING",
    "DONE": "SUCCEEDED",
    "ERROR": "FAILED",
    "CANCELED": "STOPPED",
}

VALID_DB_STATUS_ORDER = ["QUEUED", "PENDING", "RUNNING", "SUCCEEDED", "FAILED", "STOPPED"]

# Guard against the two lists silently drifting apart.
assert set(VALID_DB_STATUS_ORDER) == set(
    CLIENT_TO_DB_STATUS.values()
), "VALID_DB_STATUS_ORDER must contain exactly the DB statuses in CLIENT_TO_DB_STATUS"

FLEET_STATE_BUCKETS = ["fleet-state", "fleet-state-archive", "task-store-bucket"]
DATA_BUCKETS = ["user-data-bucket", "provider-data-bucket"]


def clear_buckets(minio_client, buckets):
    """Delete all objects in each bucket, ignoring buckets that don't exist.

    Paginates so buckets with more than one page (>1000 keys) are fully cleared,
    not just the first page.

    Args:
        minio_client: A boto3 S3 client.
        buckets: Iterable of bucket names to empty.
    """
    for bucket in buckets:
        try:
            for page in minio_client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    minio_client.delete_object(Bucket=bucket, Key=obj["Key"])
        except ClientError:
            pass


def assert_presigned_cos_redirect(serverless_client, job_id, artifact):
    """Verify a fleets job artifact endpoint 302s to a presigned COS/MinIO URL that serves the object.

    Makes the presigned-URL path explicit: the gateway signs a real SigV4 URL
    (COSClient.generate_presigned_url) against the MinIO endpoint with MinIO
    credentials, and — because the MinIO buckets are private — MinIO must
    validate that signature to return the object. A regression in presigned
    generation would surface here as a non-redirect or a 403 on the follow-up.

    Args:
        serverless_client: The ServerlessClient (for host/token/instance/channel).
        job_id: The job whose artifact to fetch.
        artifact: One of "result", "logs", "provider-logs".

    Returns:
        The requests.Response from fetching the presigned URL.
    """
    url = f"{serverless_client.host}/api/v1/jobs/{job_id}/{artifact}/"
    headers = get_headers(
        token=serverless_client.token,
        instance=serverless_client.instance,
        channel=serverless_client.channel,
    )
    resp = requests.get(url, headers=headers, allow_redirects=False, timeout=15)
    assert resp.status_code in (
        301,
        302,
        307,
        308,
    ), f"expected a presigned redirect from {artifact}, got {resp.status_code}: {resp.text[:200]}"
    location = resp.headers.get("Location", "")
    assert "X-Amz-" in location, f"{artifact} redirect is not a presigned URL: {location}"

    fetched = requests.get(location, timeout=15)
    assert (
        fetched.status_code == 200
    ), f"presigned {artifact} fetch from COS/MinIO failed: {fetched.status_code} {fetched.text[:200]}"
    return fetched


def wait_for_s3_key_substring(minio_client, bucket, substring, timeout=30):
    """Poll a bucket until any object key contains ``substring``.

    Args:
        minio_client: A boto3 S3 client.
        bucket: The bucket to search.
        substring: The substring an object key must contain.
        timeout: Maximum seconds to wait.

    Returns:
        True if a matching key appears within the timeout, else False.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for page in minio_client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
                for obj in page.get("Contents", []):
                    if substring in obj["Key"]:
                        return True
        except ClientError:
            pass
        time.sleep(1)
    return False


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


def fetch_one(pg_conn, query, params):
    """Run a query and return its first row, handling cursor lifecycle.

    Args:
        pg_conn: A psycopg2 connection.
        query: SQL query string.
        params: Query parameters tuple.

    Returns:
        The first row tuple, or None if there are no rows.
    """
    cur = pg_conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchone()
    finally:
        cur.close()


def fetch_all(pg_conn, query, params):
    """Run a query and return all rows, handling cursor lifecycle.

    Args:
        pg_conn: A psycopg2 connection.
        query: SQL query string.
        params: Query parameters tuple.

    Returns:
        A list of row tuples.
    """
    cur = pg_conn.cursor()
    try:
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        cur.close()


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
