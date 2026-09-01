"""Tests for compute_profile functionality."""

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from core.models import ComputeProfile, Job, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_ARGS_STORAGE_MOD = "core.services.storage.arguments_storage_fleets.FleetsArgumentsStorage.save"
_RESULT_STORAGE_MOD = "core.services.storage.result_storage_fleets.get_cos_client"

# Every compute profile a Fleets job can resolve to must exist as a ComputeProfile
# row, otherwise job creation is rejected as a misconfiguration. Rows are stored
# in the canonical bare (prefix-less) notation; the prefix is normalized away at
# ingest, so a prefixed submission resolves to the matching bare row.
_KNOWN_COMPUTE_PROFILES = ["24x120", "4x16", "24x120x1a100p", "8x64", "2x8"]


@pytest.fixture(autouse=True)
def mock_fleets_cos_clients():
    """Prevent Fleets storage classes from calling COS in unit tests."""
    with patch(_ARGS_STORAGE_MOD), patch(_RESULT_STORAGE_MOD):
        yield


@pytest.fixture(autouse=True)
def registered_compute_profiles():
    """Register the ComputeProfile rows the tests resolve to."""
    for profile_id in _KNOWN_COMPUTE_PROFILES:
        ComputeProfile.objects.get_or_create(compute_profile_id=profile_id)


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
    return TestUtils.get_or_create_ce_project(
        project_name="test-project",
        project_id="test-ce-project-id",
        cos_bucket_user_data_name="user-bucket",
        cos_bucket_provider_data_name="provider-bucket",
        cos_instance_name="cos-instance",
        cos_key_name="cos-key",
    )


@pytest.fixture
def program(user, ce_project):
    """Create a test program with Fleets runner for compute_profile testing."""
    return TestUtils.create_program(
        program_title="test-program",
        author=user,
        runner=Program.FLEETS,
        code_engine_project=ce_project,
    )


@override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
def test_create_job_with_compute_profile(api_client, program):
    """A prefixed submission is accepted and stored in bare notation."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": "gx3d-24x120x1a100p",
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    # The prefix is normalized away: the canonical bare form is what we store.
    assert response.data["compute_profile"] == "24x120x1a100p"

    job = Job.objects.get(id=response.data["id"])
    assert job.compute_profile == "24x120x1a100p"


@override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
def test_create_job_with_bare_compute_profile(api_client, program):
    """A bare submission is stored unchanged."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": "24x120x1a100p",
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == "24x120x1a100p"

    job = Job.objects.get(id=response.data["id"])
    assert job.compute_profile == "24x120x1a100p"


@override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
def test_create_job_without_compute_profile_uses_default(api_client, program):
    """Test creating a job without compute_profile uses system default."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == "24x120"

    # Verify job was created with default compute_profile
    job = Job.objects.get(id=response.data["id"])
    assert job.compute_profile == "24x120"


@pytest.mark.parametrize(
    "submitted,stored",
    [
        # Prefixed inputs are accepted and normalized to bare.
        ("cx3d-4x16", "4x16"),
        ("gx3d-24x120x1a100p", "24x120x1a100p"),
        ("mx2d-8x64", "8x64"),
        ("bx2d-2x8", "2x8"),
        # Bare inputs are accepted and stored unchanged.
        ("4x16", "4x16"),
        ("24x120x1a100p", "24x120x1a100p"),
    ],
)
def test_compute_profile_validation_valid_formats(api_client, program, submitted, stored):
    """Valid formats (prefixed or bare) are accepted and stored bare."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": submitted,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["compute_profile"] == stored


@pytest.mark.parametrize(
    "profile",
    [
        "invalid",
        "CX3D-4x16",  # uppercase not allowed
        "cx3d_4x16",  # underscore not allowed
        "cx3d-4",  # missing memory spec
        "4",  # missing memory spec (bare)
    ],
)
def test_compute_profile_validation_invalid_formats(api_client, program, profile):
    """Malformed compute_profile values are rejected with the format error message, no Job created."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": profile,
    }
    job_count_before = Job.objects.count()

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert f"Invalid compute profile format: '{profile}'" in response.data["message"]
    assert Job.objects.count() == job_count_before


def test_compute_profile_validation_blank_is_rejected(api_client, program):
    """An explicit blank compute_profile is rejected (by the field itself, not the format check)."""
    url = reverse("v1:programs-run")
    data = {
        "title": program.title,
        "arguments": "{}",
        "config": {},
        "compute_profile": "",
    }
    job_count_before = Job.objects.count()

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert Job.objects.count() == job_count_before


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
