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
    return Job.objects.create(program=program, author=job_author, status=Job.QUEUED)


@pytest.fixture()
def provider_job(job_author):
    provider = Provider.objects.create(name="p")
    program = Program.objects.create(title="Program", author=job_author, provider=provider)
    return Job.objects.create(program=program, author=job_author, status=Job.QUEUED)


@pytest.fixture()
def provider_admin(provider_job):
    admin = User.objects.create_user(username="admin")
    group = Group.objects.create(name="admin_group")
    admin.groups.add(group)
    provider_job.program.provider.admin_groups.add(group)
    return admin


class TestCanAccess:
    def test_validates_parameters(self, job_author, job):
        with pytest.raises(ValueError):
            JobAccessPolicies.can_access(None, job)
        with pytest.raises(ValueError):
            JobAccessPolicies.can_access(job_author, None)

    class TestLegacyGroups:
        def test_true_for_author(self, job_author, job):
            assert JobAccessPolicies.can_access(job_author, job) is True

        def test_false_for_non_author(self, other_user, job):
            assert JobAccessPolicies.can_access(other_user, job) is False

        def test_true_for_provider_admin(self, provider_admin, provider_job):
            assert JobAccessPolicies.can_access(provider_admin, provider_job) is True

    class TestRuntimeInstances:
        def test_true_when_client_has_permission(self, job_author):
            admin = User.objects.create_user(username="admin_ext")
            provider = Provider.objects.create(name="ext-provider")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            entry = FunctionAccessEntry(
                provider_name="ext-provider",
                function_title="fn",
                permissions={PLATFORM_PERMISSION_JOB_READ},
                business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
            )
            accessible = FunctionAccessResult(has_response=True, functions=[entry])
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert JobAccessPolicies.can_access(admin, provider_job, accessible_functions=accessible) is True

        def test_false_when_permission_missing(self, job_author):
            admin = User.objects.create_user(username="admin_ext2")
            provider = Provider.objects.create(name="ext-provider2")
            program = Program.objects.create(title="fn2", author=job_author, provider=provider)
            entry = FunctionAccessEntry(
                provider_name="ext-provider2",
                function_title="fn2",
                permissions={PLATFORM_PERMISSION_PROVIDER_LOGS},
                business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
            )
            accessible = FunctionAccessResult(has_response=True, functions=[entry])
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert JobAccessPolicies.can_access(admin, provider_job, accessible_functions=accessible) is False

        def test_author_always_true_regardless_of_accessible_functions(self, job_author, job):
            accessible = FunctionAccessResult(has_response=True, functions=[])
            assert JobAccessPolicies.can_access(job_author, job, accessible_functions=accessible) is True


class TestCanReadResult:
    def test_author_can_access(self, job_author, job):
        assert JobAccessPolicies.can_read_result(job_author, job) is True

    def test_non_author_cannot_access(self, other_user, job):
        assert JobAccessPolicies.can_read_result(other_user, job) is False


class TestCanSaveResult:
    def test_author_can_access(self, job_author, job):
        assert JobAccessPolicies.can_save_result(job_author, job) is True

    def test_non_author_cannot_access(self, other_user, job):
        assert JobAccessPolicies.can_save_result(other_user, job) is False


class TestCanUpdateSubStatus:
    def test_author_can_access(self, job_author, job):
        assert JobAccessPolicies.can_update_sub_status(job_author, job) is True

    def test_non_author_cannot_access(self, other_user, job):
        assert JobAccessPolicies.can_update_sub_status(other_user, job) is False


class TestCanReadUserLogs:
    def test_author_can_read(self, job_author, job):
        assert JobAccessPolicies.can_read_user_logs(job_author, job) is True

    def test_non_author_cannot_read(self, other_user, job):
        assert JobAccessPolicies.can_read_user_logs(other_user, job) is False

    def test_provider_admin_cannot_read(self, provider_admin, provider_job):
        assert JobAccessPolicies.can_read_user_logs(provider_admin, provider_job) is False


class TestCanReadProviderLogs:
    class TestLegacyGroups:
        def test_false_for_author(self, job_author, job):
            assert JobAccessPolicies.can_read_provider_logs(job_author, job) is False

        def test_false_for_non_author(self, other_user, job):
            assert JobAccessPolicies.can_read_provider_logs(other_user, job) is False

        def test_true_for_provider_admin(self, provider_admin, provider_job):
            assert JobAccessPolicies.can_read_provider_logs(provider_admin, provider_job) is True

    class TestRuntimeInstances:
        def test_true_when_client_has_permission(self, job_author):
            admin = User.objects.create_user(username="log_admin")
            provider = Provider.objects.create(name="log-provider")
            program = Program.objects.create(title="log-fn", author=job_author, provider=provider)
            entry = FunctionAccessEntry(
                provider_name="log-provider",
                function_title="log-fn",
                permissions={PLATFORM_PERMISSION_PROVIDER_LOGS},
                business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
            )
            accessible = FunctionAccessResult(has_response=True, functions=[entry])
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert (
                JobAccessPolicies.can_read_provider_logs(admin, provider_job, accessible_functions=accessible) is True
            )

        def test_false_when_client_missing_permission(self, job_author):
            admin = User.objects.create_user(username="log_admin2")
            provider = Provider.objects.create(name="log-provider2")
            program = Program.objects.create(title="log-fn2", author=job_author, provider=provider)
            entry = FunctionAccessEntry(
                provider_name="log-provider2",
                function_title="log-fn2",
                permissions={PLATFORM_PERMISSION_JOB_READ},
                business_model=Job.BUSINESS_MODEL_SUBSIDIZED,
            )
            accessible = FunctionAccessResult(has_response=True, functions=[entry])
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert (
                JobAccessPolicies.can_read_provider_logs(admin, provider_job, accessible_functions=accessible) is False
            )
