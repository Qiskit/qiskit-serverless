"""Unit tests for JobRetrieveUseCase."""

import pytest
from django.contrib.auth.models import Group, User

from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.use_cases.jobs.retrieve import JobRetrieveUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, PLATFORM_PERMISSION_JOBS_READ, Program, Provider
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
def serverless_job(author):
    program = Program.objects.create(title="my-function", author=author)
    return Job.objects.create(author=author, program=program)


@pytest.fixture()
def provider_job(author, provider):
    program = Program.objects.create(title="my-function", author=author, provider=provider)
    return Job.objects.create(author=author, program=program)


class TestJobRetrieveUseCase:
    def test_author_can_retrieve_own_job(self, author, serverless_job):
        """Job author can always retrieve their own job."""
        job = JobRetrieveUseCase().execute(serverless_job.id, author, with_result=False)
        assert job.id == serverless_job.id

    def test_non_author_cannot_retrieve_serverless_job(self, other_user, serverless_job):
        """Non-author cannot retrieve a serverless job (no provider, no permission path)."""
        with pytest.raises(JobNotFoundException):
            JobRetrieveUseCase().execute(serverless_job.id, other_user, with_result=False)

    def test_not_found_raises_exception(self, author):
        """Non-existent job ID raises JobNotFoundException."""
        import uuid

        with pytest.raises(Job.DoesNotExist):
            JobRetrieveUseCase().execute(uuid.uuid4(), author, with_result=False)

    class TestLegacyGroups:
        def test_provider_admin_can_retrieve(self, other_user, provider_job, provider_with_admin):
            """Provider admin (via Django groups) can retrieve jobs from their provider."""
            job = JobRetrieveUseCase().execute(provider_job.id, other_user, with_result=False)
            assert job.id == provider_job.id

        def test_non_admin_cannot_retrieve(self, other_user, provider_job):
            """User without admin group cannot retrieve a provider job they don't own."""
            with pytest.raises(JobNotFoundException):
                JobRetrieveUseCase().execute(provider_job.id, other_user, with_result=False)

    class TestRuntimeInstances:
        @pytest.mark.parametrize(
            "permissions,should_raise",
            [
                ({PLATFORM_PERMISSION_JOBS_READ}, False),
                ({"other-permission"}, True),
                (set(), True),
            ],
        )
        def test_access_depends_on_jobs_read_permission(self, author, other_user, provider, permissions, should_raise):
            """Non-author access requires PLATFORM_PERMISSION_JOBS_READ for the function."""
            program = Program.objects.create(title="fn", author=author, provider=provider)
            job = Job.objects.create(author=author, program=program)
            accessible = create_function_access_result("my-provider", "fn", permissions)

            if should_raise:
                with pytest.raises(JobNotFoundException):
                    JobRetrieveUseCase().execute(job.id, other_user, with_result=False, accessible_functions=accessible)
            else:
                result = JobRetrieveUseCase().execute(
                    job.id, other_user, with_result=False, accessible_functions=accessible
                )
                assert result.id == job.id

        def test_author_always_succeeds_regardless_of_accessible_functions(self, author, provider_job):
            """Author can always retrieve their job even with empty accessible_functions."""
            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
            job = JobRetrieveUseCase().execute(
                provider_job.id, author, with_result=False, accessible_functions=accessible
            )
            assert job.id == provider_job.id
