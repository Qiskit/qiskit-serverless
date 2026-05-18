"""Tests for compute_profile functionality."""

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import CodeEngineProject, Job, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    """Create an API client."""
    return APIClient()


@pytest.fixture
def user(api_client):
    """Create and authenticate a test user."""
    return TestUtils.authorize_client(user="test_user", client=api_client)


@pytest.fixture
def ce_project():
    """Create an active CodeEngineProject so select_ce_project() can find one."""
    return CodeEngineProject.objects.create(
        project_id="test-ce-project-id",
        project_name="test-project",
        region="us-east",
        resource_group_id="rg-id",
        subnet_pool_id="subnet-id",
        pds_name_state="pds-state",
        pds_name_users="pds-users",
        pds_name_providers="pds-providers",
        cos_instance_name="cos-instance",
        cos_key_name="cos-key",
        cos_bucket_user_data_name="bucket-user",
        cos_bucket_provider_data_name="bucket-provider",
        active=True,
    )


@pytest.fixture
def program(user):
    """Create a test program with Fleets runner for compute_profile testing."""
    return TestUtils.create_program(
        program_title="test-program",
        author=user,
        runner=Program.FLEETS,
    )


@override_settings(DEFAULT_COMPUTE_PROFILE="cx3d-4x16")
def test_create_job_with_compute_profile(api_client, program, ce_project):
    """Test creating a job with explicit compute_profile."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": "gx3d-24x120x1a100p",
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == "gx3d-24x120x1a100p"

    # Verify job was created with correct compute_profile
    job = Job.objects.get(id=response.data["id"])
    assert job.compute_profile == "gx3d-24x120x1a100p"


@override_settings(DEFAULT_COMPUTE_PROFILE="cx3d-4x16")
def test_create_job_without_compute_profile_uses_default(api_client, program, ce_project):
    """Test creating a job without compute_profile uses system default."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == "cx3d-4x16"

    # Verify job was created with default compute_profile
    job = Job.objects.get(id=response.data["id"])
    assert job.compute_profile == "cx3d-4x16"


@pytest.mark.parametrize(
    "profile",
    [
        "cx3d-4x16",
        "gx3d-24x120x1a100p",
        "mx2d-8x64",
        "bx2d-2x8",
    ],
)
def test_compute_profile_validation_valid_formats(api_client, program, profile, ce_project):
    """Test compute_profile validation accepts valid formats."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": profile,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == profile


@pytest.mark.parametrize(
    "profile",
    [
        "invalid",
        "CX3D-4x16",  # uppercase not allowed
        "cx3d_4x16",  # underscore not allowed
        "cx3d-4",  # missing memory spec
        "4x16",  # missing prefix
        "",  # empty string
    ],
)
def test_compute_profile_validation_invalid_formats(api_client, program, profile):
    """Test compute_profile validation rejects invalid formats."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": profile,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_job_list_includes_compute_profile(api_client, user, program):
    """Test that job list endpoint includes compute_profile."""
    # Create a job with compute_profile
    job = TestUtils.create_job(
        author=user,
        program=program,
        compute_profile="gx3d-24x120x1a100p",
    )

    url = reverse("v1:jobs-list")
    response = api_client.get(url, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "results" in response.data
    assert len(response.data["results"]) > 0

    # Response data is paginated with results field containing list of job dicts
    job_data = next((j for j in response.data["results"] if j.get("id") == str(job.id)), None)
    assert job_data is not None
    assert job_data.get("compute_profile") == "gx3d-24x120x1a100p"


def test_job_detail_includes_compute_profile(api_client, user, program):
    """Test that job detail endpoint includes compute_profile."""
    # Create a job with compute_profile
    job = TestUtils.create_job(
        author=user,
        program=program,
        compute_profile="gx3d-24x120x1a100p",
    )

    url = reverse("v1:retrieve", kwargs={"job_id": job.id})
    response = api_client.get(url, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == "gx3d-24x120x1a100p"
