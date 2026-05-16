"""Fixtures for fleets integration tests."""

import os
import uuid

import boto3
import psycopg2
import pytest
from botocore.exceptions import ClientError
from qiskit_serverless import ServerlessClient

from _helpers import DATA_BUCKETS, FLEET_STATE_BUCKETS


@pytest.fixture(scope="session")
def serverless_client():
    """Create a ServerlessClient configured from environment variables."""
    return ServerlessClient(
        token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
        host=os.environ.get("GATEWAY_HOST", "http://localhost:8000"),
        instance=os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn"),
    )


@pytest.fixture(scope="session")
def pg_conn():
    """Open a shared PostgreSQL connection for the test session."""
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
    """Create a boto3 S3 client pointing at the local MinIO instance."""
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
    for bucket in FLEET_STATE_BUCKETS + DATA_BUCKETS:
        try:
            resp = minio_client.list_objects_v2(Bucket=bucket)
            for obj in resp.get("Contents", []):
                minio_client.delete_object(Bucket=bucket, Key=obj["Key"])
        except ClientError:
            pass


@pytest.fixture()
def unique_title():
    """Generate a unique function title to avoid collisions across test runs."""
    return f"fleets-hello-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def test_provider(pg_conn):  # pylint: disable=redefined-outer-name
    """Create a Provider linked to mockgroup so provider function uploads succeed.

    Raw SQL is used because tests run out-of-process from Django. Coupled
    tables/columns: auth_group(name), api_provider(id, created, updated, name),
    api_provider_admin_groups(provider_id, group_id). Schema migrations that
    rename any of these will break this fixture silently.
    """
    provider_name = "test-provider"
    cur = pg_conn.cursor()

    # Ensure the group exists (mock auth creates it on first request, but fixture runs first)
    cur.execute("INSERT INTO auth_group (name) VALUES ('mockgroup') ON CONFLICT (name) DO NOTHING")
    cur.execute("SELECT id FROM auth_group WHERE name = 'mockgroup'")
    group_id = cur.fetchone()[0]

    # Create provider
    provider_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO api_provider (id, created, updated, name) "
        "VALUES (%s, NOW(), NOW(), %s) ON CONFLICT (name) DO UPDATE SET updated = NOW() RETURNING id",
        (provider_id, provider_name),
    )
    provider_id = cur.fetchone()[0]

    # Link mockgroup to provider admin_groups
    cur.execute(
        "INSERT INTO api_provider_admin_groups (provider_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (provider_id, group_id),
    )
    cur.close()
    return provider_name
