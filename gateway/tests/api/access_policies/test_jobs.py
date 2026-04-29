import pytest

from django.contrib.auth.models import User, Group

from api.access_policies.jobs import JobAccessPolicies
from api.domain.authorization.function_access_entry import FunctionAccessEntry
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Job, Provider, PLATFORM_PERMISSION_JOB_READ, PLATFORM_PERMISSION_PROVIDER_LOGS

pytestmark = pytest.mark.django_db


@pytest.fixture()
def job_author():
    return User.objects.create_user(username="author")


@pytest.fixture()
def other_user():
    return User.objects.create_user(username="who knows")


@pytest.fixture()
def job(job_author):
    program = Program.objects.create(title="Program", author=job_author)
    return Job.objects.create(
        program=program,
        author=job_author,
        status=Job.QUEUED,
    )


def test_can_access_validates_parameters(job_author, job):
    """ValueError when user is None, author or job is None."""
    with pytest.raises(ValueError):
        JobAccessPolicies.can_access(None, job)

    with pytest.raises(ValueError):
        JobAccessPolicies.can_access(job_author, None)


def test_can_access_returns_true_for_author(job_author, job):
    """Test that can_access returns True when user is the job author."""
    assert JobAccessPolicies.can_access(job_author, job) is True


def test_can_access_returns_false_for_non_author(other_user, job):
    """Test that can_access returns False when user is not the author."""
    assert JobAccessPolicies.can_access(other_user, job) is False


def test_can_access_returns_true_for_provider_admin(job_author):
    """Test that can_access returns True for provider admin on provider job."""
    admin_user = User.objects.create_user(username="admin")
    provider = Provider.objects.create(name="p")

    admin_group = Group.objects.create(name="same group shared")
    admin_user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    provider_program = Program.objects.create(title="Program", author=job_author, provider=provider)
    provider_job = Job.objects.create(
        program=provider_program,
        author=job_author,
        status=Job.QUEUED,
    )

    assert JobAccessPolicies.can_access(admin_user, provider_job) is True


def test_author_can_access_results_and_update_sub_status(job_author, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns True for job author."""
    assert JobAccessPolicies.can_read_result(job_author, job) is True
    assert JobAccessPolicies.can_save_result(job_author, job) is True

    assert JobAccessPolicies.can_update_sub_status(job_author, job) is True


def test_non_author_cannot_access_results_and_update_sub_status(other_user, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns False for non author."""
    assert JobAccessPolicies.can_read_result(other_user, job) is False
    assert JobAccessPolicies.can_save_result(other_user, job) is False

    assert JobAccessPolicies.can_update_sub_status(other_user, job) is False


def test_author_can_read_user_logs(job_author, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns True for job author."""
    assert JobAccessPolicies.can_read_user_logs(job_author, job) is True


def test_non_author_cannot_read_user_logs(other_user, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns False for non author."""
    assert JobAccessPolicies.can_read_user_logs(other_user, job) is False


def test_provider_admin_cannot_read_user_logs(job_author):
    """Test that can_access returns True for provider admin on provider job."""
    admin_user = User.objects.create_user(username="admin")
    provider = Provider.objects.create(name="p")

    admin_group = Group.objects.create(name="same group shared")
    admin_user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    provider_program = Program.objects.create(title="Program", author=job_author, provider=provider)
    provider_job = Job.objects.create(
        program=provider_program,
        author=job_author,
        status=Job.QUEUED,
    )

    assert JobAccessPolicies.can_read_user_logs(admin_user, provider_job) is False


def test_author_cannot_read_provider_logs(job_author, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns True for job author."""
    assert JobAccessPolicies.can_read_provider_logs(job_author, job) is False


def test_non_author_cannot_read_provider_logs(other_user, job):
    """Test that can_read_result, can_save_result and can_update_sub_status returns False for non author."""
    assert JobAccessPolicies.can_read_provider_logs(other_user, job) is False


def test_provider_admin_can_read_provider_logs(job_author):
    """Test that can_access returns True for provider admin on provider job."""
    admin_user = User.objects.create_user(username="admin")
    provider = Provider.objects.create(name="p")

    admin_group = Group.objects.create(name="same group shared")
    admin_user.groups.add(admin_group)
    provider.admin_groups.add(admin_group)

    provider_program = Program.objects.create(title="Program", author=job_author, provider=provider)
    provider_job = Job.objects.create(
        program=provider_program,
        author=job_author,
        status=Job.QUEUED,
    )

    assert JobAccessPolicies.can_read_provider_logs(admin_user, provider_job) is True


def _entry(provider_name, permissions):
    return FunctionAccessEntry(
        provider_name=provider_name,
        function_title="some-fn",
        permissions=permissions,
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )


def test_can_access_external_client_returns_true_for_provider_admin(job_author):
    """can_access True when Runtime API client has PLATFORM_PERMISSION_JOB_READ for the exact function."""
    admin_user = User.objects.create_user(username="admin_ext")
    provider = Provider.objects.create(name="ext-provider")

    provider_program = Program.objects.create(title="fn", author=job_author, provider=provider)
    entry = FunctionAccessEntry(
        provider_name="ext-provider",
        function_title="fn",
        permissions={PLATFORM_PERMISSION_JOB_READ},
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    provider_job = Job.objects.create(program=provider_program, author=job_author, status=Job.QUEUED)

    assert JobAccessPolicies.can_access(admin_user, provider_job, accessible_functions=accessible) is True


def test_can_access_external_client_returns_false_when_permission_missing(job_author):
    """can_access False when Runtime API client has no PLATFORM_PERMISSION_JOB_READ for the function."""
    admin_user = User.objects.create_user(username="admin_ext2")
    provider = Provider.objects.create(name="ext-provider2")

    provider_program = Program.objects.create(title="fn2", author=job_author, provider=provider)
    entry = FunctionAccessEntry(
        provider_name="ext-provider2",
        function_title="fn2",
        permissions={PLATFORM_PERMISSION_PROVIDER_LOGS},  # wrong permission
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    provider_job = Job.objects.create(program=provider_program, author=job_author, status=Job.QUEUED)

    assert JobAccessPolicies.can_access(admin_user, provider_job, accessible_functions=accessible) is False


def test_can_access_author_always_true_regardless_of_accessible_functions(job_author, job):
    """Author always has access regardless of accessible_functions."""
    accessible = FunctionAccessResult(has_response=True, functions=[])
    assert JobAccessPolicies.can_access(job_author, job, accessible_functions=accessible) is True


def test_can_read_provider_logs_external_client_returns_true(job_author):
    """can_read_provider_logs True when Runtime API client has PLATFORM_PERMISSION_PROVIDER_LOGS for the function."""
    admin_user = User.objects.create_user(username="log_admin")
    provider = Provider.objects.create(name="log-provider")

    provider_program = Program.objects.create(title="log-fn", author=job_author, provider=provider)
    entry = FunctionAccessEntry(
        provider_name="log-provider",
        function_title="log-fn",
        permissions={PLATFORM_PERMISSION_PROVIDER_LOGS},
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    provider_job = Job.objects.create(program=provider_program, author=job_author, status=Job.QUEUED)

    assert JobAccessPolicies.can_read_provider_logs(admin_user, provider_job, accessible_functions=accessible) is True


def test_can_read_provider_logs_external_client_returns_false_when_missing(job_author):
    """can_read_provider_logs False when Runtime API client has no PLATFORM_PERMISSION_PROVIDER_LOGS for the function."""
    admin_user = User.objects.create_user(username="log_admin2")
    provider = Provider.objects.create(name="log-provider2")

    provider_program = Program.objects.create(title="log-fn2", author=job_author, provider=provider)
    entry = FunctionAccessEntry(
        provider_name="log-provider2",
        function_title="log-fn2",
        permissions={PLATFORM_PERMISSION_JOB_READ},  # wrong permission
        business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
    )
    accessible = FunctionAccessResult(has_response=True, functions=[entry])

    provider_job = Job.objects.create(program=provider_program, author=job_author, status=Job.QUEUED)

    assert JobAccessPolicies.can_read_provider_logs(admin_user, provider_job, accessible_functions=accessible) is False
