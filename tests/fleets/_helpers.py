"""Shared helpers and constants for fleets integration tests.

Imports belong here (not in conftest.py) so test modules don't violate the
pytest idiom of treating conftest as fixtures-only.
"""

import time

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


def wait_for_s3_object(minio_client, bucket, key, timeout=30):
    """Retry until an S3 object exists, or raise after timeout."""
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
    """Retry a DB query until predicate(row) is True, or raise after timeout."""
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
