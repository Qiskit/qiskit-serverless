# pylint: disable=import-error,redefined-outer-name
"""Fixtures for file storage integration tests.

Uses MinIO as a COS emulator and the full Django stack (via pytest-django)
to test file views end-to-end: HTTP request → view → use-case → FileStorage → COS.
"""

from __future__ import annotations

import os
import sys

import boto3
import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient
from testcontainers.minio import MinioContainer

GATEWAY_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "gateway"))
sys.path.insert(0, GATEWAY_DIR)

FIXTURES_PATH = os.path.join(GATEWAY_DIR, "tests", "fixtures", "files_fixtures.json")

RAY_BUCKET = "ray-test"
FLEETS_USERS_BUCKET = "fleets-users-test"
FLEETS_PARTNERS_BUCKET = "fleets-partners-test"


@pytest.fixture(scope="session")
def minio_container():
    """Container for minio"""
    with MinioContainer() as container:
        yield container


@pytest.fixture(scope="session")
def minio_s3(minio_container):
    """S3 client connected to the MinIO container."""
    config = minio_container.get_config()
    endpoint = f"http://{config['endpoint']}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
    )


@pytest.fixture(scope="session", autouse=True)
def cos_settings(minio_container, minio_s3):
    """Create buckets and override COS settings to point at the MinIO container for the full test session."""
    config = minio_container.get_config()
    endpoint = f"http://{config['endpoint']}"
    for bucket in [RAY_BUCKET, FLEETS_USERS_BUCKET, FLEETS_PARTNERS_BUCKET]:
        minio_s3.create_bucket(Bucket=bucket)
    with override_settings(
        RAY_COS_ENDPOINT=endpoint,
        RAY_COS_ACCESS_KEY=config["access_key"],
        RAY_COS_SECRET_KEY=config["secret_key"],
        RAY_COS_BUCKET=RAY_BUCKET,
        FLEETS_USERS_COS_ENDPOINT=endpoint,
        FLEETS_USERS_COS_ACCESS_KEY=config["access_key"],
        FLEETS_USERS_COS_SECRET_KEY=config["secret_key"],
        FLEETS_USERS_COS_BUCKET=FLEETS_USERS_BUCKET,
        FLEETS_PARTNERS_COS_ENDPOINT=endpoint,
        FLEETS_PARTNERS_COS_ACCESS_KEY=config["access_key"],
        FLEETS_PARTNERS_COS_SECRET_KEY=config["secret_key"],
        FLEETS_PARTNERS_COS_BUCKET=FLEETS_PARTNERS_BUCKET,
    ):
        yield


@pytest.fixture(autouse=True)
def _setup(db):  # pylint: disable=unused-argument
    """Load DB fixtures and reset cache before each test."""
    call_command("loaddata", FIXTURES_PATH)
    cache.clear()
    from core.models import Config  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    Config.add_defaults()


@pytest.fixture
def api_client():
    """Authenticated APIClient as test_user_2 (has access to all fixture programs)."""
    from django.contrib.auth.models import User  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    client = APIClient()
    user = User.objects.get(username="test_user_2")
    client.force_authenticate(user=user)
    return client
