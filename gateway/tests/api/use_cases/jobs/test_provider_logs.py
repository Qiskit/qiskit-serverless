"""Unit tests for GetProviderJobLogsUseCase."""

import sys
import types
from unittest.mock import MagicMock, patch


def _make_pkg(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    mod.__package__ = name
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# Stub IBM COS SDK modules that are not installed in the dev environment.
# These are pulled in transitively by GetProviderJobLogsUseCase via
# core.services.runners -> core.ibm_cloud -> ibm_boto3 / ibm_botocore.
if "ibm_boto3" not in sys.modules:
    _transfer = _make_pkg("ibm_boto3.s3.transfer", TransferConfig=MagicMock())
    _s3 = _make_pkg("ibm_boto3.s3", transfer=_transfer)
    _boto3 = _make_pkg("ibm_boto3", client=MagicMock(), s3=_s3)
    sys.modules["ibm_boto3"] = _boto3
    sys.modules["ibm_boto3.s3"] = _s3
    sys.modules["ibm_boto3.s3.transfer"] = _transfer

if "ibm_botocore" not in sys.modules:

    class _ClientError(Exception):
        def __init__(self, error_response=None, operation_name=None):
            self.response = error_response or {"Error": {}}
            self.operation_name = operation_name
            super().__init__(str(error_response))

    _botocore_exc = _make_pkg("ibm_botocore.exceptions", ClientError=_ClientError)
    _botocore = _make_pkg("ibm_botocore", exceptions=_botocore_exc)
    sys.modules["ibm_botocore"] = _botocore
    sys.modules["ibm_botocore.exceptions"] = _botocore_exc


import pytest  # noqa: E402 (must come after sys.modules patching)

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


def _execute_with_fallback_logs(job_id, user, accessible_functions=None):
    """Run execute() with LogsStorage and runner mocked to fall through to job.logs."""
    with (
        patch("api.use_cases.jobs.provider_logs.LogsStorage") as mock_storage_cls,
        patch("api.use_cases.jobs.provider_logs.get_runner") as mock_get_runner,
    ):
        mock_storage_cls.return_value.get_private_logs.return_value = None
        mock_runner = MagicMock()
        mock_runner.is_active.return_value = False
        mock_get_runner.return_value = mock_runner
        return GetProviderJobLogsUseCase().execute(job_id, user, accessible_functions=accessible_functions)


class TestGetProviderJobLogsUseCase:
    def test_not_found_raises_exception(self, author):
        """Non-existent job raises JobNotFoundException."""
        import uuid

        with pytest.raises(JobNotFoundException):
            GetProviderJobLogsUseCase().execute(uuid.uuid4(), author)

    class TestLegacyGroups:
        def test_provider_admin_can_read_logs(self, other_user, provider_job, provider_with_admin):
            """Provider admin (via Django groups) can read provider logs."""
            logs = _execute_with_fallback_logs(provider_job.id, other_user)
            assert logs == provider_job.logs

        def test_non_admin_cannot_read_logs(self, other_user, provider_job):
            """Non-admin user cannot read provider logs."""
            with pytest.raises(InvalidAccessException):
                _execute_with_fallback_logs(provider_job.id, other_user)

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,grant",
            [
                ({PLATFORM_PERMISSION_PROVIDER_LOGS}, True),
                ({"other-permission"}, False),
                (set(), False),
            ],
        )
        def test_access_depends_on_provider_logs_permission(self, author, other_user, provider, permissions, grant):
            """Non-admin access requires PLATFORM_PERMISSION_PROVIDER_LOGS for the function."""
            program = Program.objects.create(title="fn", author=author, provider=provider)
            job = Job.objects.create(author=author, program=program)
            job.logs = "logs"
            job.save()
            accessible = create_function_access_result("my-provider", "fn", permissions)

            if grant:
                logs = _execute_with_fallback_logs(job.id, other_user, accessible_functions=accessible)
                assert logs == job.logs
            else:
                with pytest.raises(InvalidAccessException):
                    _execute_with_fallback_logs(job.id, other_user, accessible_functions=accessible)

        def test_author_without_provider_logs_permission_is_denied(self, author, provider_job):
            """Even the job author is denied provider logs without the permission.

            provider-logs requires explicit provider permission; there is no author bypass.
            """
            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
            with pytest.raises(InvalidAccessException):
                _execute_with_fallback_logs(provider_job.id, author, accessible_functions=accessible)
