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

"""Integration tests for FleetsRunner lifecycle via mock CE + MinIO."""

import json
import logging
import os
import time

import pytest
from qiskit_serverless import QiskitFunction

from _helpers import (
    CLIENT_TO_DB_STATUS,
    VALID_DB_STATUS_ORDER,
    is_valid_uuid,
    wait_for_db_condition,
    wait_for_s3_object,
    wait_for_terminal,
)

logger = logging.getLogger(__name__)

resources_path = os.path.join(os.path.dirname(__file__), "source_files")


def assert_client_api(job, expected_name="world", is_provider=False):
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


def assert_manifest(pg_conn, minio_client, job_id, is_provider=False):
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

    mount_paths = {vm["mount_path"] for vm in manifest["volume_mounts"]}
    if is_provider:
        expected_mounts = {"/function_user_data", "/job_user_data", "/function_provider_data", "/job_provider_data"}
    else:
        expected_mounts = {"/function_user_data", "/job_user_data"}
    assert mount_paths == expected_mounts, f"Unexpected mount paths: {mount_paths}"

    env = manifest["env_vars"]
    assert env["ENV_JOB_ID_GATEWAY"] == str(job_id)
    assert "ENV_JOB_GATEWAY_TOKEN" in env
    assert "ENV_JOB_GATEWAY_HOST" in env
    assert env["ARGUMENTS_PATH"] == "/job_user_data/arguments.json"
    assert env["PUBLIC_LOG_PATH"] == "/job_user_data/logs.log"
    assert env["RESULTS_PATH"] == "/job_user_data/results.json"
    assert "LOG_FLUSH_INTERVAL_SECONDS" in env

    if is_provider:
        assert "PRIVATE_LOG_PATH" in env, "Provider jobs must have PRIVATE_LOG_PATH"
    else:
        assert "PRIVATE_LOG_PATH" not in env, "Custom jobs should not have PRIVATE_LOG_PATH"


def assert_db_state(pg_conn, job_id, client_status):
    """Verify job, program, and event rows in the database.

    Args:
        pg_conn: A psycopg2 connection.
        job_id: The job ID to verify.
        client_status: The expected client-facing status (DONE, ERROR, etc.).
    """
    row = wait_for_db_condition(
        pg_conn,
        "SELECT status, runner, fleet_id FROM api_job WHERE id = %s",
        (job_id,),
        predicate=lambda r: r[0] in ("SUCCEEDED", "FAILED", "STOPPED"),
        timeout=30,
    )
    db_status, db_runner, db_fleet_id = row

    assert db_status == CLIENT_TO_DB_STATUS[client_status]
    assert db_runner == "fleets"
    assert is_valid_uuid(db_fleet_id)

    cur = pg_conn.cursor()
    cur.execute(
        "SELECT runner, code_engine_project_id "
        "FROM api_program WHERE id = (SELECT program_id FROM api_job WHERE id = %s)",
        (job_id,),
    )
    prog = cur.fetchone()
    assert prog is not None
    assert prog[0] == "fleets"
    assert prog[1] is not None

    cur.execute(
        "SELECT data->>'status' FROM api_jobevent WHERE job_id = %s ORDER BY created",
        (job_id,),
    )
    events = [r[0] for r in cur.fetchall() if r[0] is not None]
    cur.close()

    assert len(events) >= 2, f"Expected at least 2 events, got {len(events)}: {events}"
    assert events[0] == "QUEUED", f"First event should be QUEUED, got: {events[0]}"

    for i in range(1, len(events)):
        prev_idx = VALID_DB_STATUS_ORDER.index(events[i - 1]) if events[i - 1] in VALID_DB_STATUS_ORDER else -1
        curr_idx = VALID_DB_STATUS_ORDER.index(events[i]) if events[i] in VALID_DB_STATUS_ORDER else -1
        if prev_idx < 0 or curr_idx < 0:
            continue
        assert curr_idx >= prev_idx, f"Invalid status transition: {events[i-1]} -> {events[i]} (full: {events})"


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
        job_id, client_status = wait_for_terminal(job)
        logger.info("job %s reached terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status} for job {job_id}"

        assert_client_api(job)
        assert_manifest(pg_conn, minio_client, job_id)
        assert_db_state(pg_conn, job_id, client_status)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def test_run_provider_fleets_job(self, serverless_client, pg_conn, minio_client, unique_title, test_provider):
        """Submit a provider fleets job, assert success with provider-specific COS paths.

        Production flow: provider builds a Docker image with a Runner class at /runner/,
        registers the function with image reference, and users run it. The gateway renders
        main.tmpl (which imports Runner from the image) and uploads it + the wrapper to COS
        at submission time. The fleet-worker mock image includes the Runner package.
        """
        fn = QiskitFunction(
            title=unique_title,
            provider=test_provider,
            image="python:3.11-slim",
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(f"{test_provider}/{unique_title}")
        job = fn.run(name="provider-world")
        logger.info("job_id=%s submitted (provider=%s)", job.job_id, test_provider)
        job_id, client_status = wait_for_terminal(job)
        logger.info("job %s reached terminal: %s", job_id, client_status)

        assert client_status == "DONE", f"Expected DONE but got {client_status} for job {job_id}"

        assert_client_api(job, expected_name="provider-world", is_provider=True)
        assert_manifest(pg_conn, minio_client, job_id, is_provider=True)
        assert_db_state(pg_conn, job_id, client_status)

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
        job_id, client_status = wait_for_terminal(job)
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

    def test_cancel_running_job(self, serverless_client, pg_conn, unique_title):
        """Submit a long-running job and cancel it mid-execution — verify CANCELED status.

        ``sleep_seconds`` keeps the job RUNNING well beyond the cancel-propagation
        latency (test -> gateway -> scheduler -> mock -> COS) so the test reliably
        observes RUNNING and ``stop()`` always sees a cancellable state. The
        fleet-worker terminates the subprocess as soon as it sees the canceled key.
        """
        fn = QiskitFunction(
            title=unique_title,
            entrypoint="entrypoint.py",
            working_dir=resources_path,
            runner="fleets",
        )
        serverless_client.upload(fn)
        fn = serverless_client.function(unique_title)
        job = fn.run(name="cancel-me", sleep_seconds=120)

        deadline = time.time() + 30
        while time.time() < deadline:
            if job.status() == "RUNNING":
                break
            time.sleep(0.5)
        job.stop()

        job_id, client_status = wait_for_terminal(job)
        logger.info("job %s canceled terminal: %s", job_id, client_status)

        assert client_status == "CANCELED", f"Expected CANCELED but got {client_status} for job {job_id}"

        row = wait_for_db_condition(
            pg_conn,
            "SELECT status FROM api_job WHERE id = %s",
            (job_id,),
            predicate=lambda r: r[0] in ("SUCCEEDED", "FAILED", "STOPPED"),
            timeout=30,
        )
        assert row[0] == "STOPPED"
