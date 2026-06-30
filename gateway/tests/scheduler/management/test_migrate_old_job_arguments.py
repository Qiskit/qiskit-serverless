"""Tests for migrate_old_job_arguments command."""

import uuid
from typing import Optional

import pytest
from django.contrib.auth.models import User, Group
from django.core.management import call_command

from core.models import ComputeResource, Job, Program, Provider, Config
from core.services.storage import get_arguments_storage


@pytest.fixture(autouse=True)
def setup_config(db):
    Config.add_defaults()


def _create_test_job(
    author: str = "test_author",
    provider_admin: Optional[str] = None,
    status: str = Job.PENDING,
    compute_resource: Optional[ComputeResource] = None,
    ray_job_id: str = "test-job-id",
    gpu: bool = False,
    arguments: str = "No arguments yet.",
) -> Job:
    if compute_resource is None:
        compute_resource = ComputeResource.objects.create(title=f"test-cluster-{ray_job_id}", active=True)

    author_user, _ = User.objects.get_or_create(username=author)
    provider = None

    if provider_admin:
        provider = Provider.objects.create(name=provider_admin)
        admin_group, _ = Group.objects.get_or_create(name=provider_admin)
        admin_user, _ = User.objects.get_or_create(username=provider_admin)
        admin_user.groups.add(admin_group)
        provider.admin_groups.add(admin_group)

    program = Program.objects.create(
        title=f"program-{author_user.username}-{provider_admin or 'custom'}-{uuid.uuid4().hex[:8]}",
        author=author_user,
        provider=provider,
    )

    return Job.objects.create(
        author=author_user,
        program=program,
        status=status,
        compute_resource=compute_resource,
        ray_job_id=ray_job_id,
        gpu=gpu,
        arguments=arguments,
    )


@pytest.mark.django_db
def test_migrate_jobs_arguments_to_storage_active():
    """Tests that arguments are not migrated with an active compute resource."""
    compute_resource_active = ComputeResource.objects.create(title="test-cluster-migrate-arguments", active=True)
    test_arguments = "This is an argument for testing purposes"

    job_succeeded_active = _create_test_job(
        status=Job.SUCCEEDED, compute_resource=compute_resource_active, arguments=test_arguments
    )
    job_failed_active = _create_test_job(
        status=Job.FAILED, compute_resource=compute_resource_active, arguments=test_arguments
    )
    job_stopped_active = _create_test_job(
        status=Job.STOPPED, compute_resource=compute_resource_active, arguments=test_arguments
    )
    job_queued_active = _create_test_job(
        status=Job.QUEUED, compute_resource=compute_resource_active, arguments=test_arguments
    )
    job_running_active = _create_test_job(
        status=Job.RUNNING, compute_resource=compute_resource_active, arguments=test_arguments
    )

    call_command("migrate_old_job_arguments", max_jobs=0)

    for job in [job_succeeded_active, job_failed_active, job_stopped_active, job_queued_active, job_running_active]:
        job.refresh_from_db()
        assert job.arguments == test_arguments
        assert get_arguments_storage(job).get() is None


@pytest.mark.django_db
def test_migrate_jobs_arguments_to_storage_not_active(settings):
    """Tests that arguments are properly migrated with a not active compute resource."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-arguments", active=False)
    test_arguments = "This is an argument for testing purposes"

    job_succeeded = _create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, arguments=test_arguments)
    job_failed = _create_test_job(status=Job.FAILED, compute_resource=compute_resource, arguments=test_arguments)
    job_stopped = _create_test_job(status=Job.STOPPED, compute_resource=compute_resource, arguments=test_arguments)
    job_queued = _create_test_job(status=Job.QUEUED, compute_resource=compute_resource, arguments=test_arguments)
    job_running = _create_test_job(status=Job.RUNNING, compute_resource=compute_resource, arguments=test_arguments)

    call_command("migrate_old_job_arguments", max_jobs=0)

    for job, expected_arguments, expected_storage in [
        (job_succeeded, "", test_arguments),
        (job_failed, "", test_arguments),
        (job_stopped, "", test_arguments),
        (job_queued, test_arguments, None),
        (job_running, test_arguments, None),
    ]:
        job.refresh_from_db()
        assert job.arguments == expected_arguments
        assert get_arguments_storage(job).get() == expected_storage


@pytest.mark.django_db
def test_migrate_jobs_arguments_to_storage_too_much_elements(settings):
    """Tests that arguments are properly migrated in batches of JOB_LOGS_MIGRATION_BATCH_SIZE."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-arguments", active=False)
    test_arguments = "This is an argument for testing purposes"

    jobs = [
        _create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, arguments=test_arguments)
        for _ in range(15)
    ]

    call_command("migrate_old_job_arguments", max_jobs=0)

    for job in jobs:
        job.refresh_from_db()
    empty_arguments_count = sum(1 for job in jobs if job.arguments == "")
    assert empty_arguments_count == 15


@pytest.mark.django_db
def test_migrate_jobs_arguments_to_storage_max_jobs(settings):
    """Tests that --max-jobs 1 only migrates a single job."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-arguments", active=False)
    test_arguments = "This is an argument for testing purposes"

    jobs = [
        _create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, arguments=test_arguments)
        for _ in range(5)
    ]

    call_command("migrate_old_job_arguments", max_jobs=1)

    for job in jobs:
        job.refresh_from_db()
    empty_arguments_count = sum(1 for job in jobs if job.arguments == "")
    assert empty_arguments_count == 1
