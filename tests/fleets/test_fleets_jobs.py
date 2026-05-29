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


def _wait_for_terminal(job, timeout=120):
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


def _assert_client_api(job, expected_name="world", is_provider=False):
    """Verify result and logs via the client API.

    Args:
        job: A ServerlessJob instance in terminal state.
        expected_name: The name expected in the greeting result.
        is_provider: If True, verify log splitting (public vs private).
    """
    result = job.result(wait=False)
    assert result["greeting"] == f"Hello, {expected_name}!"
    assert result["status"] == "completed"

    user_logs = job.logs()
    logger.debug("user_logs: %r", user_logs[:200])
    assert "Hello from fleets!" in user_logs

    if is_provider:
        assert "Processing internally" not in user_logs, "User logs should not contain private lines"
        provider_logs = job.provider_logs()
        logger.debug("provider_logs: %r", provider_logs[:200])
        assert "Processing internally" in provider_logs, "Provider logs should contain all output"
    else:
        assert "Processing internally" in user_logs, "Custom jobs should have all output in user logs"


def _assert_manifest(pg_conn, minio_client, job_id, is_provider=False):
    """Verify the dispatch manifest in fleet-state-archive.

    Args:
        pg_conn: A psycopg2 connection.
        minio_client: A boto3 S3 client.
        job_id: The job ID to look up.
        is_provider: If True, verify provider-specific env vars (PRIVATE_LOG_PATH).
    """
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

    assert len(manifest["volume_mounts"]) == 2
    mount_paths = {vm["mount_path"] for vm in manifest["volume_mounts"]}
    assert mount_paths == {"/data", "/function_data"}, f"Unexpected mount paths: {mount_paths}"

    env = manifest["env_vars"]
    assert env["ENV_JOB_ID_GATEWAY"] == str(job_id)
    assert "ENV_JOB_GATEWAY_TOKEN" in env
    assert "ENV_JOB_GATEWAY_HOST" in env
    assert env["ARGUMENTS_PATH"] == "/data/arguments.json"
    assert env["PUBLIC_LOG_PATH"] == "/data/logs.log"
    assert env["RESULTS_PATH"] == "/data/results.json"
    assert "LOG_FLUSH_INTERVAL_SECONDS" in env
    assert "LOG_SIZE_LIMIT_BYTES" in env

    if is_provider:
        assert "PRIVATE_LOG_PATH" in env, "Provider jobs must have PRIVATE_LOG_PATH"
    else:
        assert "PRIVATE_LOG_PATH" not in env, "Custom jobs should not have PRIVATE_LOG_PATH"

    logger.debug("manifest env_vars keys: %s", sorted(env.keys()))


def _assert_db_state(pg_conn, job_id, client_status):  # pylint: disable=too-many-locals
    """Verify job, program, CE project, and event rows in the database.

    Args:
        pg_conn: A psycopg2 connection.
        job_id: The job ID to verify.
        client_status: The expected client-facing status (DONE, ERROR, etc.).
    """
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


def _assert_cos_objects(
    pg_conn, minio_client, job_id, provider_name=None, expected_name="world"
):  # pylint: disable=too-many-locals,too-many-positional-arguments
    """Verify arguments, entrypoint, and log objects in MinIO.

    Args:
        pg_conn: A psycopg2 connection.
        minio_client: A boto3 S3 client.
        job_id: The job ID to verify.
        provider_name: The provider name. None means custom (non-provider) job.
        expected_name: The name argument that was passed to the job.
    """
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT u.username FROM auth_user u JOIN api_job j ON j.author_id = u.id WHERE j.id = %s",
        (job_id,),
    )
    username = cur.fetchone()[0]
    cur.execute(
        "SELECT title, entrypoint FROM api_program WHERE id = (SELECT program_id FROM api_job WHERE id = %s)",
        (job_id,),
    )
    program_title, entrypoint = cur.fetchone()
    cur.close()

    is_provider = provider_name is not None

    if is_provider:
        user_prefix = f"users/{username}/provider_functions/{provider_name}/{program_title}"
        function_prefix = f"providers/{provider_name}/{program_title}"
        function_bucket = "provider-data-bucket"
    else:
        user_prefix = f"users/{username}/custom_functions/{program_title}"
        function_prefix = user_prefix
        function_bucket = "user-data-bucket"

    job_prefix = f"{user_prefix}/jobs/{job_id}"

    args_key = f"{job_prefix}/arguments.json"
    obj = wait_for_s3_object(minio_client, "user-data-bucket", args_key)
    args_content = json.loads(obj["Body"].read())
    assert args_content.get("name") == expected_name, f"Expected arguments name={expected_name!r}, got {args_content}"

    ep_key = f"{function_prefix}/{entrypoint}"
    obj = wait_for_s3_object(minio_client, function_bucket, ep_key)
    ep_content = obj["Body"].read().decode()
    assert "def main" in ep_content

    user_logs_key = f"{job_prefix}/logs.log"
    obj = wait_for_s3_object(minio_client, "user-data-bucket", user_logs_key)
    cos_user_logs = obj["Body"].read().decode()
    assert "Hello from fleets!" in cos_user_logs
    assert "Done" in cos_user_logs, "Final output missing — wrapper may not have flushed"

    if is_provider:
        assert "Processing internally" not in cos_user_logs
        provider_logs_key = f"{function_prefix}/jobs/{job_id}/logs.log"
        obj = wait_for_s3_object(minio_client, "provider-data-bucket", provider_logs_key)
        cos_provider_logs = obj["Body"].read().decode()
        assert "Processing internally" in cos_provider_logs
    else:
        assert "Processing internally" in cos_user_logs


@pytest.mark.fleets
@pytest.mark.timeout(180)
class TestFleetsJobs:
    """End-to-end tests for the fleets runner job lifecycle."""

    def test_upload_fleets_function(self, serverless_client, unique_title):
        """Upload a function with runner=fleets and verify retrieval."""
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

        _assert_client_api(job, expected_name="provider-world", is_provider=True)
        _assert_manifest(pg_conn, minio_client, job_id, is_provider=True)
        _assert_db_state(pg_conn, job_id, client_status)
        _assert_cos_objects(pg_conn, minio_client, job_id, provider_name=test_provider, expected_name="provider-world")

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
        # budget: startup_delay (2s) + immediate RuntimeError + S3 visibility
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

    def test_fleets_job_status_transitions(self, serverless_client, unique_title):
        """Verify that job.status() progresses through expected client states.

        QUEUED should be observable because the fleet-worker startup delay
        (FLEET_WORKER_STARTUP_DELAY_SEC) keeps the job in QUEUED/PENDING
        longer than the 1s poll interval here.
        """
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)
        job = fn.run(name="transitions")

        observed = set()
        deadline = time.time() + 120
        while time.time() < deadline:
            status = job.status()
            observed.add(status)
            if status in ("DONE", "ERROR", "CANCELED"):
                break
            time.sleep(1)

        assert "QUEUED" in observed, f"Never saw QUEUED state, observed: {observed}"
        assert "DONE" in observed, f"Job did not succeed, observed: {observed}"

    def test_run_fleets_job_no_arguments(self, serverless_client, unique_title):
        """Submit a fleets job without arguments and verify empty args flow."""
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint_no_args.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)
        job = fn.run()

        job_id, client_status = _wait_for_terminal(job)
        logger.info("job %s no-args terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status} for job {job_id}"

        result = job.result(wait=False)
        assert result["received_args"] == {}, f"Expected empty args, got {result['received_args']}"
        assert result["status"] == "completed"

    def test_run_fleets_job_log_truncation(self, serverless_client, pg_conn, minio_client, unique_title):
        """Submit a job that exceeds LOG_SIZE_LIMIT_BYTES and verify truncation."""
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint_large_log.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)
        job = fn.run(target_bytes=150000)
        logger.info("job_id=%s submitted (large log test)", job.job_id)
        job_id, client_status = _wait_for_terminal(job, timeout=180)
        logger.info("job %s terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status}"

        user_logs = job.logs()
        assert (
            "[Logs exceeded maximum allowed size" in user_logs
        ), f"Truncation header not found in logs (len={len(user_logs)})"
        assert "discarding the oldest entries first.]" in user_logs
        assert "FINAL_LINE" in user_logs, "Final output line should survive truncation"
        assert "LOG_LINE_000001" not in user_logs, "First log line should have been truncated"

        cur = pg_conn.cursor()
        cur.execute(
            "SELECT u.username FROM auth_user u " "JOIN api_job j ON j.author_id = u.id WHERE j.id = %s",
            (job_id,),
        )
        username = cur.fetchone()[0]
        cur.execute(
            "SELECT title FROM api_program WHERE id = " "(SELECT program_id FROM api_job WHERE id = %s)",
            (job_id,),
        )
        program_title = cur.fetchone()[0]
        cur.close()

        log_key = f"users/{username}/custom_functions/{program_title}/jobs/{job_id}/logs.log"
        obj = wait_for_s3_object(minio_client, "user-data-bucket", log_key)
        cos_log_content = obj["Body"].read().decode()
        cos_log_size = len(cos_log_content)

        limit = 51200
        max_allowed = limit + 200
        logger.info("COS log size: %d bytes (limit=%d)", cos_log_size, limit)
        assert cos_log_size <= max_allowed, f"COS log ({cos_log_size} bytes) exceeds limit+overhead ({max_allowed})"
        assert (
            cos_log_size > limit * 0.9
        ), f"COS log ({cos_log_size} bytes) unexpectedly small — truncation may not have occurred"

        assert "[Logs exceeded maximum allowed size" in cos_log_content
        assert "FINAL_LINE" in cos_log_content
        assert "LOG_LINE_000001" not in cos_log_content
