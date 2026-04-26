"""Tests for migrate_old_job_logs command."""

import uuid
from typing import Optional

import pytest
from django.contrib.auth.models import User, Group
from django.core.management import call_command

from core.models import ComputeResource, Job, Program, Provider, Config
from core.services.storage.logs_storage import LogsStorage


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
    logs: str = "No logs yet.",
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
        logs=logs,
    )


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_active():
    """Tests that logs are not migrated with an active compute resource."""
    compute_resource_active = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=True)
    test_logs = "This is a log for testing pourposes"

    job_succeeded_active = _create_test_job(
        status=Job.SUCCEEDED, compute_resource=compute_resource_active, logs=test_logs
    )
    job_failed_active = _create_test_job(status=Job.FAILED, compute_resource=compute_resource_active, logs=test_logs)
    job_stopped_active = _create_test_job(status=Job.STOPPED, compute_resource=compute_resource_active, logs=test_logs)
    job_queued_active = _create_test_job(status=Job.QUEUED, compute_resource=compute_resource_active, logs=test_logs)
    job_running_active = _create_test_job(status=Job.RUNNING, compute_resource=compute_resource_active, logs=test_logs)

    call_command("migrate_old_job_logs")

    for job in [job_succeeded_active, job_failed_active, job_stopped_active, job_queued_active, job_running_active]:
        job.refresh_from_db()
        assert job.logs == test_logs
        assert LogsStorage(job).get_public_logs() is None


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_active_with_provider():
    """Tests that logs are not migrated with an active compute resource belonging to a provider function."""
    compute_resource_active = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=True)
    test_logs = "This is a log for testing pourposes"

    jobs = [
        _create_test_job(
            status=status, compute_resource=compute_resource_active, logs=test_logs, provider_admin=f"test_provider_{i}"
        )
        for i, status in enumerate([Job.SUCCEEDED, Job.FAILED, Job.STOPPED, Job.QUEUED, Job.RUNNING], 1)
    ]

    call_command("migrate_old_job_logs")

    for job in jobs:
        job.refresh_from_db()
        assert job.logs == test_logs
        assert LogsStorage(job).get_public_logs() is None
        assert LogsStorage(job).get_private_logs() is None


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_not_active(settings):
    """Tests that logs are properly migrated with a not active compute resource."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=False)
    test_logs = "This is a log for testing pourposes"

    job_succeeded = _create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, logs=test_logs)
    job_failed = _create_test_job(status=Job.FAILED, compute_resource=compute_resource, logs=test_logs)
    job_stopped = _create_test_job(status=Job.STOPPED, compute_resource=compute_resource, logs=test_logs)
    job_queued = _create_test_job(status=Job.QUEUED, compute_resource=compute_resource, logs=test_logs)
    job_running = _create_test_job(status=Job.RUNNING, compute_resource=compute_resource, logs=test_logs)

    call_command("migrate_old_job_logs")

    for job, expected_logs, expected_storage in [
        (job_succeeded, "", test_logs),
        (job_failed, "", test_logs),
        (job_stopped, "", test_logs),
        (job_queued, test_logs, None),
        (job_running, test_logs, None),
    ]:
        job.refresh_from_db()
        assert job.logs == expected_logs
        assert LogsStorage(job).get_public_logs() == expected_storage


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_not_active_with_provider(settings):
    """Tests that logs are properly migrated with a not active compute resource belonging to a provider function."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=False)
    test_logs = "This is a log for testing pourposes"

    job_succeeded = _create_test_job(
        status=Job.SUCCEEDED, compute_resource=compute_resource, logs=test_logs, provider_admin="test_provider_1"
    )
    job_failed = _create_test_job(
        status=Job.FAILED, compute_resource=compute_resource, logs=test_logs, provider_admin="test_provider_2"
    )
    job_stopped = _create_test_job(
        status=Job.STOPPED, compute_resource=compute_resource, logs=test_logs, provider_admin="test_provider_3"
    )
    job_queued = _create_test_job(
        status=Job.QUEUED, compute_resource=compute_resource, logs=test_logs, provider_admin="test_provider_4"
    )
    job_running = _create_test_job(
        status=Job.RUNNING, compute_resource=compute_resource, logs=test_logs, provider_admin="test_provider_5"
    )

    call_command("migrate_old_job_logs")

    for job, expected_logs, expected_public, expected_private in [
        (job_succeeded, "", None, test_logs),
        (job_failed, "", None, test_logs),
        (job_stopped, "", None, test_logs),
        (job_queued, test_logs, None, None),
        (job_running, test_logs, None, None),
    ]:
        job.refresh_from_db()
        assert job.logs == expected_logs
        assert LogsStorage(job).get_public_logs() == expected_public
        assert LogsStorage(job).get_private_logs() == expected_private


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_too_much_elements(settings):
    """Tests that logs are properly migrated in batches of JOB_LOGS_MIGRATION_BATCH_SIZE."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=False)
    test_logs = "This is a log for testing pourposes"

    jobs = [
        _create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, logs=test_logs) for _ in range(15)
    ]

    call_command("migrate_old_job_logs")

    for job in jobs:
        job.refresh_from_db()
    empty_logs_count = sum(1 for job in jobs if job.logs == "")
    assert empty_logs_count == 15


@pytest.mark.django_db
def test_migrate_jobs_logs_to_storage_max_jobs(settings):
    """Tests that --max-jobs 1 only migrates a single job."""
    settings.JOB_LOGS_MIGRATION_BATCH_SIZE = 10
    compute_resource = ComputeResource.objects.create(title="test-cluster-migrate-logs", active=False)
    test_logs = "This is a log for testing pourposes"

    jobs = [_create_test_job(status=Job.SUCCEEDED, compute_resource=compute_resource, logs=test_logs) for _ in range(5)]

    call_command("migrate_old_job_logs", max_jobs=1)

    for job in jobs:
        job.refresh_from_db()
    empty_logs_count = sum(1 for job in jobs if job.logs == "")
    assert empty_logs_count == 1
