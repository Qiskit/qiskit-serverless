"""Unit tests for GetJobsUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.get_jobs import GetJobsUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture
def provider():
    return Provider.objects.create(name="my-provider")


class TestGetJobsUseCase:
    def test_returns_own_jobs(self, user, other_user):
        program = Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        own_job = TestUtils.create_job(author=user, program=program)
        TestUtils.create_job(author=other_user, program=program)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = list(GetJobsUseCase().execute(user, accessible, program.id))

        assert len(result) == 1
        assert result[0].id == own_job.id

    def test_provider_admin_sees_all_jobs(self, user, other_user, provider):
        group = TestUtils.get_or_create_group("my-provider")
        TestUtils.add_user_to_group(user, group)
        provider.admin_groups.add(group)
        program = Program.objects.create(
            title="provider-fn", author=other_user, provider=provider, entrypoint="main.py"
        )
        job_a = TestUtils.create_job(author=user, program=program)
        job_b = TestUtils.create_job(author=other_user, program=program)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = list(GetJobsUseCase().execute(user, accessible, program.id))

        assert {j.id for j in result} == {job_a.id, job_b.id}

    def test_non_admin_sees_only_own_jobs(self, user, other_user, provider):
        program = Program.objects.create(
            title="provider-fn", author=other_user, provider=provider, entrypoint="main.py"
        )
        own_job = TestUtils.create_job(author=user, program=program)
        TestUtils.create_job(author=other_user, program=program)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = list(GetJobsUseCase().execute(user, accessible, program.id))

        assert len(result) == 1
        assert result[0].id == own_job.id

    def test_raises_not_found_when_program_missing(self, user):
        import uuid

        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetJobsUseCase().execute(user, accessible, uuid.uuid4())
