"""Tests for Code Engine related models."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from core.models import Job, Program, CodeEngineProject, ComputeResource

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(username="test_user")


@pytest.fixture
def program(db, user):
    """Create a test program."""
    return Program.objects.create(title="Test Program", author=user)


@pytest.fixture
def ce_project(db):
    """Create a test Code Engine project."""
    return CodeEngineProject.objects.create(
        project_id="ce-test-123",
        project_name="test-project",
        region="us-east",
        resource_group_id="rg-123",
        subnet_pool_id="subnet-123",
        pds_name_state="pds-state",
        pds_name_users="pds-users",
        pds_name_providers="pds-providers",
    )


# CodeEngineProject Tests


def test_code_engine_project_creation(ce_project):
    """Test creating a CodeEngineProject."""
    assert ce_project.project_id == "ce-test-123"
    assert ce_project.project_name == "test-project"
    assert ce_project.region == "us-east"
    assert ce_project.active is True


def test_code_engine_project_unique_project_id(db, ce_project):
    """Test that project_id must be unique."""
    with pytest.raises(IntegrityError):
        CodeEngineProject.objects.create(
            project_id="ce-test-123",  # Duplicate
            project_name="another-project",
            region="eu-de",
            resource_group_id="rg-456",
            subnet_pool_id="subnet-456",
            pds_name_state="pds-state-2",
            pds_name_users="pds-users-2",
            pds_name_providers="pds-providers-2",
        )


def test_code_engine_project_str_representation(ce_project):
    """Test the string representation."""
    assert str(ce_project) == "test-project (us-east)"


# Job with Code Engine Tests

def test_job_with_code_engine_project(user, program, ce_project):
    """Test creating a Job with Code Engine project."""
    job = Job.objects.create(
        author=user,
        program=program,
        code_engine_project=ce_project,
        fleet_id="fleet-abc-123",
    )

    assert job.code_engine_project == ce_project
    assert job.fleet_id == "fleet-abc-123"
    assert job.compute_resource is None
    assert job.ray_job_id is None


def test_job_with_ray_compute_resource(db, user, program):
    """Test creating a Job with Ray compute resource."""
    compute_resource = ComputeResource.objects.create(
        title="test-ray-cluster",
        host="ray://localhost:10001",
    )

    job = Job.objects.create(
        author=user,
        program=program,
        compute_resource=compute_resource,
        ray_job_id="ray-job-456",
    )

    assert job.compute_resource == compute_resource
    assert job.ray_job_id == "ray-job-456"
    assert job.code_engine_project is None
    assert job.fleet_id is None


def test_job_code_engine_project_set_null_on_delete(user, program, ce_project):
    """Test that Job.code_engine_project is set to NULL when project is deleted."""
    job = Job.objects.create(
        author=user,
        program=program,
        code_engine_project=ce_project,
        fleet_id="fleet-cascade-123",
    )

    ce_project.delete()
    job.refresh_from_db()

    assert job.code_engine_project is None
    assert job.fleet_id == "fleet-cascade-123" #fleet_id is not set to None
