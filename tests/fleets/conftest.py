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

"""Fixtures for fleets integration tests."""

import os
import uuid

import boto3
import psycopg2
import pytest
from qiskit_serverless import QiskitFunction, ServerlessClient

from _helpers import DATA_BUCKETS, FLEET_STATE_BUCKETS, clear_buckets, wait_for_terminal

resources_path = os.path.join(os.path.dirname(__file__), "source_files")


@pytest.fixture(scope="session")
def serverless_client():
    """Create a ServerlessClient configured from environment variables.

    Returns:
        A ServerlessClient instance pointing at the local gateway.
    """
    return ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
        instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
    )


@pytest.fixture(scope="session")
def pg_conn():
    """Open a shared PostgreSQL connection for the test session.

    Returns:
        A psycopg2 connection with autocommit enabled.
    """
    conn = psycopg2.connect(
        host=os.environ.get("DATABASE_HOST", "localhost"),
        port=int(os.environ.get("DATABASE_PORT", "5432")),
        dbname=os.environ.get("DATABASE_NAME", "serverlessdb"),
        user=os.environ.get("DATABASE_USER", "serverlessuser"),
        password=os.environ.get("DATABASE_PASSWORD", "serverlesspassword"),
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def minio_client():
    """Create a boto3 S3 client pointing at the local MinIO instance.

    Returns:
        A boto3 S3 client configured for MinIO.
    """
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        region_name="us-east-1",
    )


@pytest.fixture(scope="session", autouse=True)
def cleanup_minio(minio_client):  # pylint: disable=redefined-outer-name
    """Clear fleet-state and data buckets at the start of each test run."""
    clear_buckets(minio_client, FLEET_STATE_BUCKETS + DATA_BUCKETS)


@pytest.fixture(scope="session", autouse=True)
def warm_pipeline(serverless_client, cleanup_minio):  # pylint: disable=redefined-outer-name,unused-argument
    """Warm the whole fleets pipeline (scheduler -> worker -> s3fs) once, before timed tests.

    The first job after ``docker compose up`` pays a one-time cold-start cost:
    the scheduler and fleet-worker containers boot (Django start, migrate lock,
    s3fs FUSE mount) and the run script only waits for the gateway and MinIO —
    not the scheduler or worker. On a slow CI runner that cold-start can consume
    a per-test ``wait_for_terminal`` budget, so the *first* timed test flakes
    while later (warm) tests pass. Running one throwaway job to completion here
    absorbs that cold-start into session setup with a generous one-time budget,
    keeping every per-test budget fair. If the pipeline never comes up this
    fails loudly at setup rather than as a confusing mid-suite timeout.
    """
    title = f"fleets-warmup-{uuid.uuid4().hex[:8]}"
    fn = QiskitFunction(
        title=title,
        entrypoint="entrypoint.py",
        working_dir=resources_path,
        runner="fleets",
    )
    serverless_client.upload(fn)
    fn = serverless_client.function(title)
    job = fn.run(name="warmup")
    _, status = wait_for_terminal(job, timeout=300)
    assert status == "DONE", (
        f"Fleets pipeline warm-up job did not finish (last status={status}); "
        "scheduler/worker/s3fs did not come up — check container logs."
    )


@pytest.fixture(autouse=True)
def cleanup_fleet_state_after_test(minio_client):  # pylint: disable=redefined-outer-name
    """Clear the fleet-state buckets after each test.

    Clears the manifest bucket (fleet-state, which the worker polls) plus the
    archive and task-store buckets so COS queue keys do not accumulate
    unbounded across a session (each job uses a fresh fleet_id, so clearing is
    safe and keeps the harness from depending on fleet_id uniqueness alone).
    """
    yield
    clear_buckets(minio_client, FLEET_STATE_BUCKETS)


@pytest.fixture()
def unique_title():
    """Generate a unique function title to avoid collisions across test runs.

    Returns:
        A string like ``fleets-hello-<8 hex chars>``.
    """
    return f"fleets-hello-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def test_provider(pg_conn):  # pylint: disable=redefined-outer-name
    """Create a Provider linked to mockgroup so provider function uploads succeed.

    Intentionally a persistent, idempotent seed (no teardown): all three inserts
    use ON CONFLICT, the provider name is a fixed constant reused across runs,
    and provider programs/jobs FK-reference it, so deleting it on teardown would
    be FK-fragile. It is seeded once per session and left in place.

    Raw SQL is used because tests run out-of-process from Django. Coupled
    tables/columns: auth_group(name), api_provider(id, created, updated, name),
    api_provider_admin_groups(provider_id, group_id).

    Args:
        pg_conn: The shared PostgreSQL connection fixture.

    Returns:
        The provider name string.
    """
    provider_name = "test-provider"
    cur = pg_conn.cursor()

    cur.execute("INSERT INTO auth_group (name) VALUES ('mockgroup') ON CONFLICT (name) DO NOTHING")
    cur.execute("SELECT id FROM auth_group WHERE name = 'mockgroup'")
    group_id = cur.fetchone()[0]

    provider_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO api_provider (id, created, updated, name) "
        "VALUES (%s, NOW(), NOW(), %s) ON CONFLICT (name) DO UPDATE SET updated = NOW() RETURNING id",
        (provider_id, provider_name),
    )
    provider_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO api_provider_admin_groups (provider_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (provider_id, group_id),
    )
    cur.close()
    return provider_name
