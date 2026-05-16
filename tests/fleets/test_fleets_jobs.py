"""Integration tests for FleetsRunner lifecycle via mock CE + MinIO."""

import json
import logging
import os
import time
import uuid

import pytest
from qiskit_serverless import QiskitFunction

from _helpers import (
    CLIENT_TO_DB_STATUS,
    VALID_DB_STATUS_ORDER,
    wait_for_s3_object,
    wait_for_db_condition,
)

logger = logging.getLogger(__name__)

resources_path = os.path.join(os.path.dirname(__file__), "source_files")


def is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _wait_for_terminal(job, timeout=120):
    """Poll job.status() until terminal. Returns (job_id, client_status)."""
    job_id = job.job_id
    deadline = time.time() + timeout
    client_status = None
    while time.time() < deadline:
        client_status = job.status()
        if client_status in ("DONE", "ERROR", "CANCELED"):
            return job_id, client_status
        time.sleep(2)
    raise AssertionError(f"Job {job_id} did not reach terminal state within {timeout}s, last status: {client_status}")


def _assert_client_api(job, expected_name="world", check_provider_logs=False):
    """Verify result and logs via the client API."""
    result = job.result(wait=False)
    assert result["greeting"] == f"Hello, {expected_name}!"
    assert result["status"] == "completed"

    user_logs = job.logs()
    logger.debug("user_logs: %r", user_logs[:200])
    assert "Hello from fleets!" in user_logs
    assert "Processing internally" not in user_logs, "User logs should not contain private lines"

    if check_provider_logs:
        provider_logs = job.provider_logs()
        logger.debug("provider_logs: %r", provider_logs[:200])
        assert "Processing internally" in provider_logs, "Provider logs should contain all output"


def _assert_manifest(pg_conn, minio_client, job_id):
    """Verify the dispatch manifest in fleet-state-archive."""
    row_for_fleet = wait_for_db_condition(
        pg_conn,
        "SELECT fleet_id FROM api_job WHERE id = %s",
        (job_id,),
        predicate=lambda r: r[0] is not None,
        timeout=15,
    )
    fleet_id = row_for_fleet[0]
    manifest_obj = wait_for_s3_object(minio_client, "fleet-state-archive", f"{fleet_id}.json", timeout=15)
    manifest = json.loads(manifest_obj["Body"].read())
    assert manifest["fleet_id"] == fleet_id
    assert manifest["job_id"] == str(job_id)
    assert "volume_mounts" in manifest
    assert "env_vars" in manifest
    assert "run_commands" in manifest
    assert len(manifest["volume_mounts"]) == 3
    assert manifest["env_vars"]["ENV_JOB_ID_GATEWAY"] == str(job_id)
    assert "ENV_JOB_GATEWAY_TOKEN" in manifest["env_vars"]
    assert "ENV_JOB_GATEWAY_HOST" in manifest["env_vars"]
    assert "ARGUMENTS_PATH" in manifest["env_vars"]
    logger.debug("manifest env_vars keys: %s", sorted(manifest["env_vars"].keys()))


def _assert_db_state(pg_conn, job_id, client_status):  # pylint: disable=too-many-locals
    """Verify job, program, CE project, and event rows in the database."""
    row = wait_for_db_condition(
        pg_conn,
        "SELECT status, runner, fleet_id, ray_job_id, code_engine_project_id FROM api_job WHERE id = %s",
        (job_id,),
        predicate=lambda r: r[0] in ("SUCCEEDED", "FAILED", "STOPPED"),
        timeout=30,
    )
    db_status, db_runner, db_fleet_id, db_ray_job_id, db_ce_project_id = row

    assert db_status == CLIENT_TO_DB_STATUS[client_status]
    assert db_runner == "fleets"
    assert db_fleet_id is not None
    assert is_valid_uuid(db_fleet_id)
    assert db_ray_job_id is None
    assert db_ce_project_id is not None

    cur = pg_conn.cursor()
    cur.execute(
        "SELECT runner, entrypoint FROM api_program WHERE id = (SELECT program_id FROM api_job WHERE id = %s)",
        (job_id,),
    )
    prog = cur.fetchone()
    assert prog is not None
    assert prog[0] == "fleets"
    assert prog[1] == "entrypoint.py"

    cur.execute(
        "SELECT cos_bucket_user_data_name, cos_bucket_provider_data_name, active "
        "FROM api_codeengineproject WHERE id = %s",
        (db_ce_project_id,),
    )
    ce = cur.fetchone()
    assert ce is not None
    assert ce[0] == "user-data-bucket"
    assert ce[1] == "provider-data-bucket"
    assert ce[2] is True

    cur.execute(
        "SELECT data->>'status' FROM api_jobevent WHERE job_id = %s ORDER BY created",
        (job_id,),
    )
    events = [r[0] for r in cur.fetchall() if r[0] is not None]
    cur.close()

    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}: {events}"
    assert events[0] == "QUEUED", f"First event should be QUEUED, got: {events[0]}"

    for i in range(1, len(events)):
        prev_status = events[i - 1]
        curr_status = events[i]
        if prev_status not in VALID_DB_STATUS_ORDER or curr_status not in VALID_DB_STATUS_ORDER:
            continue
        prev_idx = VALID_DB_STATUS_ORDER.index(prev_status)
        curr_idx = VALID_DB_STATUS_ORDER.index(curr_status)
        assert curr_idx >= prev_idx, f"Invalid status transition: {prev_status} -> {curr_status} (full: {events})"
    logger.debug("events progression: %s", " -> ".join(events))


def _assert_cos_objects(pg_conn, minio_client, job_id, provider_name="default"):  # pylint: disable=too-many-locals
    """Verify arguments, entrypoint, and log objects in MinIO."""
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT u.username FROM auth_user u JOIN api_job j ON j.author_id = u.id WHERE j.id = %s",
        (job_id,),
    )
    username = cur.fetchone()[0]
    cur.execute(
        "SELECT title FROM api_program WHERE id = (SELECT program_id FROM api_job WHERE id = %s)",
        (job_id,),
    )
    program_title = cur.fetchone()[0]
    cur.close()

    user_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}"
    provider_prefix = f"providers/{provider_name}/{program_title}"

    args_key = f"{user_prefix}/jobs/{job_id}/arguments.json"
    obj = wait_for_s3_object(minio_client, "user-data-bucket", args_key)
    args_content = json.loads(obj["Body"].read())
    assert "name" in args_content or "arguments" in args_content

    ep_key = f"{provider_prefix}/entrypoint.py"
    obj = wait_for_s3_object(minio_client, "provider-data-bucket", ep_key)
    ep_content = obj["Body"].read().decode()
    assert "def main" in ep_content

    user_logs_key = f"{user_prefix}/jobs/{job_id}/logs.log"
    obj = wait_for_s3_object(minio_client, "user-data-bucket", user_logs_key)
    cos_user_logs = obj["Body"].read().decode()
    assert "Hello from fleets!" in cos_user_logs
    assert "Processing internally" not in cos_user_logs

    provider_logs_key = f"{provider_prefix}/jobs/{job_id}/logs.log"
    obj = wait_for_s3_object(minio_client, "provider-data-bucket", provider_logs_key)
    cos_provider_logs = obj["Body"].read().decode()
    assert "Processing internally" in cos_provider_logs


@pytest.mark.fleets
@pytest.mark.timeout(180)
class TestFleetsJobs:
    """End-to-end tests for the fleets runner job lifecycle."""

    def test_upload_fleets_function(self, serverless_client, unique_title):
        """Upload a function with runner=fleets."""
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        retrieved = serverless_client.function(unique_title)
        assert retrieved is not None

    def test_run_fleets_job(self, serverless_client, pg_conn, minio_client, unique_title):
        """Submit a fleets job, assert success, verify via API + DB + COS."""
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)
        job = fn.run(name="world")
        logger.info("job_id=%s submitted, waiting for terminal state", job.job_id)
        job_id, client_status = _wait_for_terminal(job)
        logger.info("job %s reached terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status} for job {job_id}"

        _assert_client_api(job)
        _assert_manifest(pg_conn, minio_client, job_id)
        _assert_db_state(pg_conn, job_id, client_status)
        _assert_cos_objects(pg_conn, minio_client, job_id)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def test_run_provider_fleets_job(self, serverless_client, pg_conn, minio_client, unique_title, test_provider):
        """Submit a provider fleets job, assert success with provider-specific COS paths."""
        fn = QiskitFunction(
            title=unique_title,
            provider=test_provider,
            entrypoint="entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(f"{test_provider}/{unique_title}")
        job = fn.run(name="provider-world")
        logger.info("job_id=%s submitted (provider=%s)", job.job_id, test_provider)
        job_id, client_status = _wait_for_terminal(job)
        logger.info("job %s reached terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status} for job {job_id}"

        _assert_client_api(job, expected_name="provider-world", check_provider_logs=True)
        _assert_manifest(pg_conn, minio_client, job_id)
        _assert_db_state(pg_conn, job_id, client_status)
        _assert_cos_objects(pg_conn, minio_client, job_id, provider_name=test_provider)

        cur = pg_conn.cursor()
        cur.execute(
            "SELECT p.name FROM api_provider p "
            "JOIN api_program prog ON prog.provider_id = p.id "
            "WHERE prog.id = (SELECT program_id FROM api_job WHERE id = %s)",
            (job_id,),
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None
        assert row[0] == test_provider

    def test_run_fleets_job_failure(self, serverless_client, pg_conn, unique_title):
        """Submit a fleets job with a bad entrypoint and assert FAILED state."""
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="bad_entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)

        submitted_at = time.time()
        job = fn.run()
        logger.info("job_id=%s submitted (bad entrypoint)", job.job_id)
        job_id, client_status = _wait_for_terminal(job)
        elapsed = time.time() - submitted_at
        logger.info("job %s terminal: %s in %.1fs", job_id, client_status, elapsed)

        assert client_status == "ERROR", f"Expected ERROR but got {client_status} for job {job_id}"

        # Guard against a timeout being misclassified as FAILED. Expected
        # budget: startup_delay (~5s) + immediate RuntimeError + S3 visibility
        # (<5s) + scheduler poll (~10-30s). 90s leaves CI headroom while still
        # catching regressions where failure detection slows significantly.
        assert elapsed < 90, f"Job took {elapsed:.1f}s — likely a timeout, not a real failure"

        user_logs = job.logs()
        logger.debug("user_logs: %r", user_logs[:300])
        assert (
            "Intentional failure for testing" in user_logs
        ), f"Expected RuntimeError message in logs, got: {user_logs[:500]!r}"

        row = wait_for_db_condition(
            pg_conn,
            "SELECT status FROM api_job WHERE id = %s",
            (job_id,),
            predicate=lambda r: r[0] in ("SUCCEEDED", "FAILED", "STOPPED"),
            timeout=30,
        )
        assert row[0] == "FAILED"
