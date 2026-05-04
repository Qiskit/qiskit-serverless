import pytest

from django.contrib.auth.models import User, Group

from api.access_policies.jobs import JobAccessPolicies
from api.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Job, Provider, PLATFORM_PERMISSION_JOB_READ, PLATFORM_PERMISSION_PROVIDER_LOGS
from tests.api.conftest import create_function_access_result

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
        """Raises ValueError if user or job is None."""
        with pytest.raises(ValueError):
            JobAccessPolicies.can_access(None, job)

        with pytest.raises(ValueError):
            JobAccessPolicies.can_access(job_author, None)

    class TestLegacyGroups:
        """This tests use the Django groups where a user is a provider admin if there is a group in common"""

        def test_true_for_author(self, job_author, job):
            """Job author can always access their own job."""
            assert JobAccessPolicies.can_access(job_author, job) is True

        def test_false_for_non_author(self, other_user, job):
            """Non-author user cannot access a job they did not create."""
            assert JobAccessPolicies.can_access(other_user, job) is False

        def test_true_for_provider_admin(self, provider_admin, provider_job):
            """Provider admin can access jobs belonging to their provider."""
            assert JobAccessPolicies.can_access(provider_admin, provider_job) is True

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,expected",
            [
                ({PLATFORM_PERMISSION_JOB_READ}, True),
                ({"other-permission"}, False),
            ],
        )
        def test_access_depends_on_job_read_permission(self, job_author, permissions, expected):
            """Access is granted if the entry includes PLATFORM_PERMISSION_JOB_READ for the function."""
            admin = User.objects.create_user(username="admin_ext")
            provider = Provider.objects.create(name="ext-provider")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            accessible = create_function_access_result("ext-provider", "fn", permissions)
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert JobAccessPolicies.can_access(admin, provider_job, accessible_functions=accessible) is expected

        def test_author_always_true_regardless_of_accessible_functions(self, job_author, job):
            """Author can access their job even when accessible_functions returns no entries."""
            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
            assert JobAccessPolicies.can_access(job_author, job, accessible_functions=accessible) is True


class TestCanReadResult:
    @pytest.mark.parametrize(
        "user_fixture,expected",
        [
            ("job_author", True),
            ("other_user", False),
        ],
    )
    def test_access(self, request, user_fixture, expected, job):
        """Only the job author can read the result."""
        user = request.getfixturevalue(user_fixture)
        assert JobAccessPolicies.can_read_result(user, job) is expected


class TestCanSaveResult:
    @pytest.mark.parametrize(
        "user_fixture,expected",
        [
            ("job_author", True),
            ("other_user", False),
        ],
    )
    def test_access(self, request, user_fixture, expected, job):
        """Only the job author can save the result."""
        user = request.getfixturevalue(user_fixture)
        assert JobAccessPolicies.can_save_result(user, job) is expected


class TestCanUpdateSubStatus:
    @pytest.mark.parametrize(
        "user_fixture,expected",
        [
            ("job_author", True),
            ("other_user", False),
        ],
    )
    def test_access(self, request, user_fixture, expected, job):
        """Only the job author can update the sub-status."""
        user = request.getfixturevalue(user_fixture)
        assert JobAccessPolicies.can_update_sub_status(user, job) is expected


class TestCanReadUserLogs:
    @pytest.mark.parametrize(
        "user_fixture,expected",
        [
            ("job_author", True),
            ("other_user", False),
        ],
    )
    def test_access(self, request, user_fixture, expected, job):
        """Only the job author can read user-facing logs."""
        user = request.getfixturevalue(user_fixture)
        assert JobAccessPolicies.can_read_user_logs(user, job) is expected

    def test_provider_admin_cannot_read(self, provider_admin, provider_job):
        """Provider admin cannot read user logs even for jobs under their provider."""
        assert JobAccessPolicies.can_read_user_logs(provider_admin, provider_job) is False


class TestCanReadProviderLogs:
    class TestLegacyGroups:
        def test_false_for_author(self, job_author, job):
            """Job author cannot read provider logs for non-provider jobs."""
            assert JobAccessPolicies.can_read_provider_logs(job_author, job) is False

        def test_false_for_non_author(self, other_user, job):
            """Unrelated user cannot read provider logs."""
            assert JobAccessPolicies.can_read_provider_logs(other_user, job) is False

        def test_true_for_provider_admin(self, provider_admin, provider_job):
            """Provider admin can read provider logs for jobs under their provider."""
            assert JobAccessPolicies.can_read_provider_logs(provider_admin, provider_job) is True

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,expected",
            [
                ({PLATFORM_PERMISSION_PROVIDER_LOGS}, True),
                ({"other-permission"}, False),
            ],
        )
        def test_logs_depend_on_provider_logs_permission(self, job_author, permissions, expected):
            """Provider log access is granted if the entry includes PLATFORM_PERMISSION_PROVIDER_LOGS."""
            admin = User.objects.create_user(username="log_admin")
            provider = Provider.objects.create(name="log-provider")
            program = Program.objects.create(title="log-fn", author=job_author, provider=provider)
            accessible = create_function_access_result("log-provider", "log-fn", permissions)
            provider_job = Job.objects.create(program=program, author=job_author, status=Job.QUEUED)
            assert (
                JobAccessPolicies.can_read_provider_logs(admin, provider_job, accessible_functions=accessible)
                is expected
            )
