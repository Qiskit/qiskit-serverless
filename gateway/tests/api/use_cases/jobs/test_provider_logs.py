"""Unit tests for GetProviderJobLogsUseCase."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User

from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.use_cases.jobs.provider_logs import GetProviderJobLogsUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, PLATFORM_PERMISSION_PROVIDER_LOGS, Program, Provider
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture()
def author():
    return User.objects.create_user(username="author")


@pytest.fixture()
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture()
def provider_with_admin(provider, other_user):
    g = Group.objects.create(name="my-provider-group")
    other_user.groups.add(g)
    provider.admin_groups.add(g)
    return provider


@pytest.fixture()
def provider_job(author, provider):
    program = Program.objects.create(title="my-function", author=author, provider=provider)
    job = Job.objects.create(author=author, program=program)
    job.logs = "some provider logs"
    job.save()
    return job


def _execute_provider_logs_use_case(job_id, user, logs_content="provider logs from COS", accessible_functions=None):
    """Run execute() with LogsStorage returning logs from COS (happy path)."""
    with patch("api.use_cases.jobs.provider_logs.LogsStorage") as mock_storage_cls:
        mock_storage_cls.return_value.get_private_logs.return_value = logs_content
        return GetProviderJobLogsUseCase().execute(job_id, user, accessible_functions=accessible_functions)


class TestGetProviderJobLogsUseCase:
    def test_not_found_raises_exception(self, author):
        """Non-existent job raises JobNotFoundException."""
        import uuid

        with pytest.raises(JobNotFoundException):
            _execute_provider_logs_use_case(uuid.uuid4(), author)

    class TestLegacyGroups:
        def test_provider_admin_can_read_logs(self, other_user, provider_job, provider_with_admin):
            """Provider admin (via Django groups) can read provider logs."""
            logs = _execute_provider_logs_use_case(provider_job.id, other_user)
            assert logs == "provider logs from COS"

        def test_non_admin_cannot_read_logs(self, other_user, provider_job):
            """Non-admin user cannot read provider logs."""
            with pytest.raises(InvalidAccessException):
                _execute_provider_logs_use_case(provider_job.id, other_user)

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,grant",
            [
                ({PLATFORM_PERMISSION_PROVIDER_LOGS}, True),
                ({"other-permission"}, False),
                (set(), False),
            ],
        )
        def test_access_depends_on_provider_logs_permission(self, other_user, provider_job, permissions, grant):
            """Non-admin access requires PLATFORM_PERMISSION_PROVIDER_LOGS for the function."""
            accessible = create_function_access_result("my-provider", "my-function", permissions)

            if grant:
                logs = _execute_provider_logs_use_case(provider_job.id, other_user, accessible_functions=accessible)
                assert logs == "provider logs from COS"
            else:
                with pytest.raises(InvalidAccessException):
                    _execute_provider_logs_use_case(provider_job.id, other_user, accessible_functions=accessible)

        def test_author_without_provider_logs_permission_is_denied(self, author, provider_job):
            """Even the job author is denied provider logs without the permission.

            provider-logs requires explicit provider permission; there is no author bypass.
            """
            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
            with pytest.raises(InvalidAccessException):
                _execute_provider_logs_use_case(provider_job.id, author, accessible_functions=accessible)
