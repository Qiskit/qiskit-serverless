"""Tests for the job status token and GET /jobs/{id}/status/."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core import signing
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from api.services.authentication.job_status_token import issue_job_status_token
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job
from tests.utils import TestUtils


def _retrieve(user, job):
    client = APIClient()
    token = MagicMock()
    token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
    client.force_authenticate(user=user, token=token)
    return client.get(reverse("v1:retrieve", args=[job.id]) + "?with_result=false")


def _status(job, token=None, **headers):
    if token is not None:
        headers["HTTP_X_JOB_STATUS_TOKEN"] = token
    return APIClient().get(reverse("v1:jobs-status", args=[job.id]), **headers)


@pytest.fixture(name="author")
def fixture_author(db):
    return User.objects.create(username="token_author")


@pytest.fixture(name="program")
def fixture_program(author):
    return TestUtils.create_program(program_title="token-function", author=author)


@pytest.fixture(name="job")
def fixture_job(author, program):
    return TestUtils.create_job(author=author, program=program, status=Job.RUNNING, sub_status=Job.MAPPING)


def test_retrieve_gives_the_author_a_token_for_a_job_that_has_not_ended(author, job):
    response = _retrieve(author, job)

    assert response.status_code == status.HTTP_200_OK
    assert response["X-Job-Status-Token"]
    assert response["Cache-Control"] == "no-store"


def test_retrieve_gives_no_token_for_an_ended_job(author, job):
    job.status = Job.SUCCEEDED
    job.save()

    assert "X-Job-Status-Token" not in _retrieve(author, job)


def test_retrieve_gives_no_token_to_someone_who_is_not_the_author(job):
    admin = User.objects.create(username="token_admin", is_staff=True, is_superuser=True)
    with patch("api.use_cases.jobs.retrieve.JobAccessPolicies.can_access", return_value=True):
        response = _retrieve(admin, job)

    assert response.status_code == status.HTTP_200_OK
    assert "X-Job-Status-Token" not in response


def test_status_reads_the_job_in_one_query_with_no_api_key_auth(author, job):
    token = _retrieve(author, job)["X-Job-Status-Token"]

    with (
        patch("api.authentication.AuthenticationUseCase") as api_key_auth,
        CaptureQueriesContext(connection) as captured,
    ):
        response = _status(job, token)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == {"status": Job.RUNNING, "sub_status": Job.MAPPING}
    assert response["Cache-Control"] == "no-store"
    assert len(captured) == 2  # the user, then the job
    api_key_auth.assert_not_called()


def test_status_refuses_a_missing_tampered_or_expired_token_and_an_api_key(author, job):
    token = issue_job_status_token(author.id, job.id)

    assert _status(job).status_code == status.HTTP_401_UNAUTHORIZED
    assert _status(job, token + "x").status_code == status.HTTP_401_UNAUTHORIZED
    assert _status(job, HTTP_AUTHORIZATION="Bearer an-api-key").status_code == status.HTTP_401_UNAUTHORIZED
    with patch("api.services.authentication.job_status_token.signing.loads", side_effect=signing.SignatureExpired):
        assert _status(job, token).status_code == status.HTTP_401_UNAUTHORIZED


def test_status_refuses_a_token_for_another_job(author, program, job):
    other = TestUtils.create_job(author=author, program=program, status=Job.RUNNING)

    assert _status(other, issue_job_status_token(author.id, job.id)).status_code == status.HTTP_404_NOT_FOUND


def test_status_refuses_a_token_of_an_inactive_user(author, job):
    token = issue_job_status_token(author.id, job.id)
    author.is_active = False
    author.save()

    assert _status(job, token).status_code == status.HTTP_401_UNAUTHORIZED
