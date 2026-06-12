# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for log use case behavior specific to Fleet jobs.

Fleet logs are pre-filtered by the in-container wrapper and stored in COS.
The use cases read directly from COS; if nothing is there yet they return
"No logs yet." — there is no runner fallback for Fleet jobs.
"""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User

from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.use_cases.jobs.get_logs_response import GetLogsResponse
from api.use_cases.jobs.provider_logs import GetProviderJobLogsUseCase
from core.models import PLATFORM_PERMISSION_PROVIDER_LOGS, Program, Provider
from tests.utils import TestUtils, create_function_access_result

pytestmark = pytest.mark.django_db

_GET_LOGS_MOD = "api.use_cases.jobs.get_logs"
_PROVIDER_LOGS_MOD = "api.use_cases.jobs.provider_logs"


@pytest.fixture
def ce_project():
    return TestUtils.get_or_create_ce_project(
        project_name="test-project",
        project_id="test-ce-project-id",
        cos_bucket_user_data_name="user-bucket",
        cos_bucket_provider_data_name="provider-bucket",
        cos_instance_name="cos-instance",
        cos_key_name="cos-key",
    )


@pytest.fixture
def author():
    return User.objects.create_user(username="fleet-author")


@pytest.fixture
def provider():
    return Provider.objects.create(name="fleet-provider")


@pytest.fixture
def provider_admin(provider):
    user = User.objects.create_user(username="fleet-provider-admin")
    g = Group.objects.create(name="fleet-provider-group")
    user.groups.add(g)
    provider.admin_groups.add(g)
    return user


@pytest.fixture
def fleet_custom_job(author, ce_project):
    program = TestUtils.create_program(
        program_title="fleet-func",
        author=author,
        runner=Program.FLEETS,
        code_engine_project=ce_project,
    )
    return TestUtils.create_job(author=author, program=program)


@pytest.fixture
def fleet_provider_job(author, provider, ce_project):
    program = TestUtils.create_program(
        program_title="fleet-provider-func",
        author=author,
        provider=provider,
        runner=Program.FLEETS,
        code_engine_project=ce_project,
    )
    return TestUtils.create_job(author=author, program=program)


# ── GetJobLogsUseCase — Fleet ─────────────────────────────────────────────────


class TestGetJobLogsUseCaseFleet:
    def _execute(self, job, user, cos_url=None):
        with patch(f"{_GET_LOGS_MOD}.get_logs_storage") as mock_storage:
            mock_storage.return_value.get_public_logs_url.return_value = cos_url
            return GetJobLogsUseCase().execute(job.id, user)

    def test_returns_redirect_url_when_logs_available(self, fleet_custom_job, author):
        """When COS object exists, use case returns GetLogsResponse with redirect_url."""
        url = "https://cos.example.com/logs.log?sig=abc"
        result = self._execute(fleet_custom_job, author, cos_url=url)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url == url
        assert result.raw_log is None

    def test_returns_redirect_url_for_provider_job(self, fleet_provider_job, author):
        """Provider Fleet job: use case returns GetLogsResponse with redirect_url."""
        url = "https://cos.example.com/provider-logs.log?sig=xyz"
        result = self._execute(fleet_provider_job, author, cos_url=url)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url == url

    def test_no_cos_logs_returns_empty_get_logs_response(self, fleet_custom_job, author):
        """When COS has no logs yet, returns GetLogsResponse() with both fields None."""
        result = self._execute(fleet_custom_job, author, cos_url=None)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url is None
        assert result.raw_log is None

    def test_no_cos_logs_provider_job_returns_empty_get_logs_response(self, fleet_provider_job, author):
        """Provider Fleet job with no logs: returns GetLogsResponse() with both fields None."""
        result = self._execute(fleet_provider_job, author, cos_url=None)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url is None
        assert result.raw_log is None


# ── GetProviderJobLogsUseCase — Fleet ─────────────────────────────────────────


class TestGetProviderJobLogsUseCaseFleet:
    def _execute(self, job, user, cos_url=None, accessible_functions=None):
        with patch(f"{_PROVIDER_LOGS_MOD}.get_logs_storage") as mock_storage:
            mock_storage.return_value.get_private_logs_url.return_value = cos_url
            return GetProviderJobLogsUseCase().execute(job.id, user, accessible_functions=accessible_functions)

    def test_returns_redirect_url_when_logs_available(self, fleet_provider_job, provider_admin):
        """When COS private log exists, returns GetLogsResponse with redirect_url."""
        url = "https://cos.example.com/private-logs.log?sig=xyz"
        result = self._execute(fleet_provider_job, provider_admin, cos_url=url)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url == url
        assert result.raw_log is None

    def test_no_cos_logs_returns_empty_get_logs_response(self, fleet_provider_job, provider_admin):
        """When COS has no private logs yet, returns GetLogsResponse() with both fields None."""
        result = self._execute(fleet_provider_job, provider_admin, cos_url=None)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url is None
        assert result.raw_log is None

    def test_accessible_functions_grant_access(self, fleet_provider_job, author):
        """Provider logs accessible via FunctionAccessResult with correct permission."""
        accessible = create_function_access_result(
            "fleet-provider", "fleet-provider-func", {PLATFORM_PERMISSION_PROVIDER_LOGS}
        )
        url = "https://cos.example.com/private-logs.log?sig=granted"
        result = self._execute(fleet_provider_job, author, cos_url=url, accessible_functions=accessible)
        assert isinstance(result, GetLogsResponse)
        assert result.redirect_url == url
