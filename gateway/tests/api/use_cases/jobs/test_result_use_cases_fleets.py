"""Tests for GetJobResultUseCase behavior specific to Fleet jobs."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User

from api.use_cases.jobs.get_result import GetJobResultUseCase
from api.use_cases.jobs.result_fetch_result import ResultFetchResult
from core.models import Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db

_GET_RESULT_MOD = "api.use_cases.jobs.get_result"


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
    return User.objects.create_user(username="fleet-result-author")


@pytest.fixture
def fleet_job(author, ce_project):
    program = TestUtils.create_program(
        program_title="fleet-func",
        author=author,
        runner=Program.FLEETS,
    )
    return TestUtils.create_job(author=author, program=program, code_engine_project=ce_project)


class TestGetJobResultUseCaseFleet:
    def _execute(self, job, user, cos_url=None):
        with patch(f"{_GET_RESULT_MOD}.get_result_storage") as mock_storage:
            mock_storage.return_value.get_url.return_value = cos_url
            return GetJobResultUseCase().execute(job.id, user)

    def test_returns_redirect_url_when_result_available(self, fleet_job, author):
        """When COS object exists, use case returns ResultFetchResult with redirect_url."""
        url = "https://cos.example.com/results.json?sig=abc"
        result = self._execute(fleet_job, author, cos_url=url)
        assert isinstance(result, ResultFetchResult)
        assert result.redirect_url == url
        assert result.raw_result is None

    def test_returns_empty_result_when_no_result(self, fleet_job, author):
        """When COS has no result yet, returns ResultFetchResult() with both fields None."""
        result = self._execute(fleet_job, author, cos_url=None)
        assert isinstance(result, ResultFetchResult)
        assert result.redirect_url is None
        assert result.raw_result is None
