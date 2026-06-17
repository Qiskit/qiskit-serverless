"""Unit tests for RunFunctionUseCase."""

import pytest
from django.contrib.auth.models import User
from unittest.mock import patch

from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.authentication.channel import Channel
from api.use_cases.programs.run import RunFunctionUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program

pytestmark = pytest.mark.django_db

VALID_DATA = {"title": "my-fn", "arguments": "{}", "config": {}}


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class TestRunFunctionUseCase:
    def test_creates_job_for_own_function(self, user):
        function = Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        carrier = {}

        job = RunFunctionUseCase().execute(
            user,
            accessible,
            {"title": "my-fn", "arguments": "{}", "config": {}},
            channel=Channel.IBM_QUANTUM_PLATFORM,
            token="tok",
            instance=None,
            account_id=None,
            carrier=carrier,
        )

        assert job.program.title == "my-fn"
        assert job.program.id == function.id
        assert job.author == user

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            RunFunctionUseCase().execute(
                user,
                accessible,
                {"title": "nonexistent-fn", "arguments": "{}", "config": {}},
                channel="ibm_quantum",
                token="tok",
                instance=None,
                account_id=None,
                carrier={},
            )

    def test_raises_function_disabled(self, user):
        Program.objects.create(
            title="my-fn",
            author=user,
            entrypoint="main.py",
            disabled=True,
            disabled_message="maintenance",
        )
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionDisabledException):
            RunFunctionUseCase().execute(
                user,
                accessible,
                {"title": "my-fn", "arguments": "{}", "config": {}},
                channel="ibm_quantum",
                token="tok",
                instance=None,
                account_id=None,
                carrier={},
            )

    def test_raises_active_job_limit_exceeded(self, user):
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with patch("api.use_cases.programs.run.active_jobs_limit_reached", return_value=True):
            with pytest.raises(ActiveJobLimitExceeded):
                RunFunctionUseCase().execute(
                    user,
                    accessible,
                    {"title": "my-fn", "arguments": "{}", "config": {}},
                    channel="ibm_quantum",
                    token="tok",
                    instance=None,
                    account_id=None,
                    carrier={},
                )

    def test_raises_not_found_when_no_permission_for_custom_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            RunFunctionUseCase().execute(
                user,
                accessible,
                {"title": "my-fn", "arguments": "{}", "config": {}},
                channel="ibm_quantum",
                token="tok",
                instance=None,
                account_id=None,
                carrier={},
            )
