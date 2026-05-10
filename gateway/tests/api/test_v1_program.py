"""Tests program APIs."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from tests.utils import create_function_access_result
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import (
    Job,
    JobEvent,
    PLATFORM_PERMISSION_JOBS_READ,
    PLATFORM_PERMISSION_WRITE,
    PLATFORM_PERMISSION_READ,
    PLATFORM_PERMISSION_RUN,
    Program,
)
from core.services.storage import get_arguments_storage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestProgramApiLegacyGroupsPermissions:
    """Programs endpoints with legacy Django groups authorization (use_legacy_authorization=True)."""

    @pytest.fixture
    def client(self):
        return APIClient()

    @pytest.fixture
    def authorize_legacy(self, client):
        """Authorize with legacy groups (use_legacy_authorization=True) — no runtime instances client."""
        from api.domain.authentication.channel import Channel
        from core.domain.authorization.function_access_result import FunctionAccessResult

        def _do(username):
            user, _ = User.objects.get_or_create(username=username)
            token = MagicMock()
            token.accessible_functions = FunctionAccessResult(use_legacy_authorization=True)
            token.channel = Channel.LOCAL
            token.token = b"test-token"
            token.instance = None
            client.force_authenticate(user=user, token=token)
            return user

        return _do

    class TestRunProgram:
        def test_run_own_function(self, client, authorize_legacy):
            """run() grants access to the function author via Django groups fallback."""
            user = authorize_legacy("test-user")
            TestUtils.create_program(program_title="my-func", author=user)

            response = client.post(
                "/api/v1/programs/run/",
                data={"title": "my-func", "arguments": "{}", "config": {"workers": 1}},
                format="json",
            )

            assert response.status_code == status.HTTP_200_OK

        def test_grant_run_provider_function_via_group(self, client, authorize_legacy):
            """run() grants access to provider function when user is in the run_program group."""
            user = authorize_legacy("test-user")
            TestUtils.get_or_create_group(group="runner", permissions=[["run_program", "api", "program"]])
            TestUtils.add_user_to_group(user, "runner")
            TestUtils.create_program(
                program_title="provider-func", author="other-author", provider="my-provider", instances=["runner"]
            )

            response = client.post(
                "/api/v1/programs/run/",
                data={"title": "provider-func", "provider": "my-provider", "arguments": "{}", "config": {"workers": 1}},
                format="json",
            )

            assert response.status_code == status.HTTP_200_OK

        def test_revoke_run_provider_function_without_group(self, client, authorize_legacy):
            """run() returns 404 when user has no group permission for the provider function."""
            authorize_legacy("test-user")
            TestUtils.create_program(program_title="provider-func", author="other-author", provider="my-provider")

            response = client.post(
                "/api/v1/programs/run/",
                data={"title": "provider-func", "provider": "my-provider", "arguments": "{}", "config": {"workers": 1}},
                format="json",
            )

            assert response.status_code == status.HTTP_404_NOT_FOUND

    class TestUpload:
        def test_grant_upload_provider_function_via_admin_group(self, client, authorize_legacy):
            """upload() grants access when user belongs to the provider admin_groups."""
            user = authorize_legacy("test-user")
            TestUtils.get_or_create_group(group="admin-group")
            TestUtils.add_user_to_group(user, "admin-group")
            TestUtils.get_or_create_provider(provider="my-provider", admin_group="admin-group")

            response = client.post(
                "/api/v1/programs/upload/",
                data={"title": "my-func", "provider": "my-provider", "dependencies": "[]", "entrypoint": "main.py"},
            )

            assert response.status_code == status.HTTP_200_OK

        def test_revoke_upload_provider_function_without_admin_group(self, client, authorize_legacy):
            """upload() returns 404 when user is not in the provider admin_groups."""
            authorize_legacy("test-user")
            TestUtils.get_or_create_provider(provider="my-provider")

            response = client.post(
                "/api/v1/programs/upload/",
                data={"title": "my-func", "provider": "my-provider", "dependencies": "[]", "entrypoint": "main.py"},
            )

            assert response.status_code == status.HTTP_404_NOT_FOUND

    class TestGetJobs:
        def test_provider_admin_sees_all_jobs(self, client, authorize_legacy):
            """get_jobs() returns all jobs when user is in the provider admin_groups."""
            user = authorize_legacy("admin-user")
            TestUtils.get_or_create_group(group="admin-group")
            TestUtils.add_user_to_group(user, "admin-group")
            program = TestUtils.create_program(
                program_title="my-func", author="func-author", provider="my-provider", instances=["admin-group"]
            )
            TestUtils.get_or_create_provider(provider="my-provider", admin_group="admin-group")
            other_user, _ = User.objects.get_or_create(username="other-user")
            TestUtils.create_job(author=user, program=program, status=Job.QUEUED)
            TestUtils.create_job(author=other_user, program=program, status=Job.QUEUED)

            response = client.get(f"/api/v1/programs/{program.id}/get_jobs/", format="json")

            assert response.status_code == status.HTTP_200_OK
            assert len(response.data) == 2

        def test_non_admin_sees_only_own_jobs(self, client, authorize_legacy):
            """get_jobs() returns only own jobs when user is not in the provider admin_groups."""
            user = authorize_legacy("test-user")
            program = TestUtils.create_program(program_title="my-func", author="func-author", provider="my-provider")
            other_user, _ = User.objects.get_or_create(username="other-user")
            TestUtils.create_job(author=user, program=program, status=Job.QUEUED)
            TestUtils.create_job(author=other_user, program=program, status=Job.QUEUED)

            response = client.get(f"/api/v1/programs/{program.id}/get_jobs/", format="json")

            assert response.status_code == status.HTTP_200_OK
            assert len(response.data) == 1


class TestProgramApi(APITestCase):
    """TestProgramApi."""

    def setUp(self):
        # pylint: disable=invalid-name
        """Set up test fixtures and media root path."""
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name
        self.LIMITS_ACTIVE_JOBS_PER_USER = 2
        self.runner_permission = ["run_program", "api", "program"]
        self.viewer_permission = ["view_program", "api", "program"]

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

    def test_programs_non_auth_user(self):
        """Tests program list non-authorized."""
        url = reverse("v1:programs-list")
        response = self.client.get(url, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_programs_list(self):
        """
        Tests programs list returns only programs user has access to (as an author).
        Since user doesn't belong to any group, it will only be self-authored programs.
        """

        user = TestUtils.authorize_client(user="test_user", client=self.client)

        # Create 3 programs for test_user
        program_names = ["ProgramLocked", "Program", "ProgramLocked2"]
        for program_name in program_names:
            disabled = "Locked" in program_name
            TestUtils.create_program(program_title=program_name, author=user, disabled=disabled)

        # Create program for another user (not accessible to test_user)
        TestUtils.create_program(program_title="OtherUserProgram", author="test_user_2")

        # no filter applied - all program `test_user` has view permission (owned program in this case) are returned.
        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        assert programs_response.status_code == status.HTTP_200_OK
        assert len(programs_response.data) == 3
        for resp_data in programs_response.data:
            assert resp_data.get("title") in program_names

    def test_provider_programs_list(self):
        """Tests programs list returns only programs user has access permission for."""

        user = TestUtils.authorize_client(user="test_user_2", client=self.client)

        # Create provider program accessible to test_user_2 as author
        TestUtils.create_program(
            program_title="Docker-Image-Program",
            author=user,
            provider="default",
        )

        # Create program by different author (not accessible)
        TestUtils.create_program(
            program_title="Other-Program",
            author="other_user",
            provider="other_provider",
        )

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        assert programs_response.status_code == status.HTTP_200_OK
        assert len(programs_response.data) == 1
        assert programs_response.data[0].get("provider") == "default"
        assert programs_response.data[0].get("title") == "Docker-Image-Program"

    def test_provider_programs_catalog_list(self):
        """
        Tests catalog filter programs list for group access programs. Catalog filter only returns providers
        functions that user has access: author has permissions for it (by group/instance) and the function has a
        provider assigned.
        """

        user = TestUtils.authorize_client(user="test_user_4", client=self.client)
        TestUtils.get_or_create_group(group="runner", permissions=[self.runner_permission])
        # Add user to runner group for RUN_PROGRAM_PERMISSION
        TestUtils.add_user_to_group(user=user, group="runner")

        # Create 2 provider programs with ibm provider that user has access to
        TestUtils.create_program(
            program_title="Docker-Image-Program-2",
            author="test_user_3",
            provider="ibm",
            instances=["runner"],
        )
        TestUtils.create_program(
            program_title="Docker-Image-Program-3",
            author="test_user_3",
            provider="ibm",
            instances=["runner", "viewer"],
        )

        # Create a provider programs with ibm provider that `test_user_4` has no access to
        # - should not appear in catalog
        TestUtils.create_program(
            program_title="Other-Program",
            author="test_user_3",
            provider="ibm",
            instances=["premium"],
        )

        # Create serverless program (no provider) - should not appear in catalog
        TestUtils.create_program(
            program_title="Other-Program",
            author="test_user_3",
            instances=["runner"],
        )

        programs_response = self.client.get(reverse("v1:programs-list"), {"filter": "catalog"}, format="json")

        assert programs_response.status_code == status.HTTP_200_OK
        assert len(programs_response.data) == 2
        for data in programs_response.data:
            assert data.get("title") in [
                "Docker-Image-Program-2",
                "Docker-Image-Program-3",
            ]
            assert data.get("provider") == "ibm"
        assert programs_response.data[0].get("title") != programs_response.data[1].get("title")

    def test_provider_programs_serverless_list(self):
        """Tests programs list for serverless list. The return criteria is the user is the author of the function and
        there is no provider"""

        user = TestUtils.authorize_client(user="test_user_3", client=self.client)

        # Create serverless program (author=user, no provider) - have permission to run
        TestUtils.create_program(
            program_title="Program",
            author=user,
            entrypoint="program.py",
            artifact="path",
        )

        # Create provider program by same user (should not appear in serverless filter)
        TestUtils.create_program(
            program_title="Provider-Program",
            author=user,
            provider="default",
        )

        programs_response = self.client.get(reverse("v1:programs-list"), {"filter": "serverless"}, format="json")

        assert programs_response.status_code == status.HTTP_200_OK
        assert len(programs_response.data) == 1
        assert programs_response.data[0].get("title") == "Program"

    def test_run(self):
        """Tests run existing authorized."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = TestUtils.authorize_client(user="test_user_3", client=self.client)
            TestUtils.get_or_create_group(group="runner", permissions=[self.runner_permission])
            # Add user to runner group for trial access
            TestUtils.add_user_to_group(user, "runner")

            # Create program with trial_instances
            TestUtils.create_program(
                program_title="Program",
                author=user,
                entrypoint="program.py",
                artifact="path",
                trial_instances=["runner"],
            )

            arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
            programs_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "Program",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )
            job_id = programs_response.data.get("id")
            job = Job.objects.get(id=job_id)
            env_vars = json.loads(job.env_vars)

            assert job.status == Job.QUEUED
            assert job.trial is True
            assert job.business_model == BusinessModel.TRIAL
            assert env_vars["ENV_ACCESS_TRIAL"] == "True"
            assert job.config.min_workers == 1
            assert job.config.max_workers == 5
            assert job.config.workers is None
            assert job.config.auto_scaling is True

            program = Program.objects.get(title="Program", author=user)
            arguments_storage = get_arguments_storage(user.username, program)
            stored_arguments = arguments_storage.get(job.id)

            assert stored_arguments == arguments

            # Verify arguments are stored in the correct folder path
            expected_arguments_path = os.path.join(self.MEDIA_ROOT, user.username, "arguments")
            assert arguments_storage.absolute_path == expected_arguments_path

            job_events = JobEvent.objects.filter(job=job_id)
            assert len(job_events) == 1
            assert job_events[0].event_type == JobEventType.STATUS_CHANGE
            assert job_events[0].data["status"] == Job.QUEUED
            assert job_events[0].origin == JobEventOrigin.API
            assert job_events[0].context == JobEventContext.RUN_PROGRAM

    def test_provider_run(self):
        """Tests run existing authorized."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = TestUtils.authorize_client(user="test_user_2", client=self.client)
            TestUtils.get_or_create_provider(provider="default")

            # Create program with provider and env_vars
            TestUtils.create_program(
                program_title="Docker-Image-Program",
                author=user,
                provider="default",
                env_vars=json.dumps({"PROGRAM_ENV1": "VALUE1", "PROGRAM_ENV2": "VALUE2"}),
            )

            arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
            programs_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "Docker-Image-Program",
                    "provider": "default",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )

            job_id = programs_response.data.get("id")
            job = Job.objects.get(id=job_id)
            env_vars = json.loads(job.env_vars)

            assert job.status == Job.QUEUED
            assert job.trial is False
            assert job.business_model == BusinessModel.SUBSIDIZED
            assert env_vars["PROGRAM_ENV1"] == "VALUE1"
            assert env_vars["PROGRAM_ENV2"] == "VALUE2"
            assert job.config.min_workers == 1
            assert job.config.max_workers == 5
            assert job.config.workers is None
            assert job.config.auto_scaling is True

            program = Program.objects.get(title="Docker-Image-Program", author=user)
            arguments_storage = get_arguments_storage(user.username, program)
            stored_arguments = arguments_storage.get(job.id)

            assert stored_arguments == arguments

            # Verify arguments are stored in the correct folder path for provider
            expected_arguments_path = os.path.join(
                self.MEDIA_ROOT,
                user.username,
                "default",
                "Docker-Image-Program",
                "arguments",
            )
            assert arguments_storage.absolute_path == expected_arguments_path

            job_events = JobEvent.objects.filter(job=job_id)
            assert len(job_events) == 1
            assert job_events[0].event_type == JobEventType.STATUS_CHANGE
            assert job_events[0].data["status"] == Job.QUEUED
            assert job_events[0].origin == JobEventOrigin.API
            assert job_events[0].context == JobEventContext.RUN_PROGRAM

    def test_active_jobs_queue_limit(self):
        """Tests queue limit."""

        def run_program():
            """Runs program"""
            job_kwargs = {
                "title": "Docker-Image-Program-Test",
                "provider": "default",
                "arguments": json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"}),
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": True,
                },
            }

            return self.client.post(
                "/api/v1/programs/run/",
                data=job_kwargs,
                format="json",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(
                LIMITS_ACTIVE_JOBS_PER_USER=self.LIMITS_ACTIVE_JOBS_PER_USER,
                MEDIA_ROOT=temp_dir,
            ):
                user = TestUtils.authorize_client(user="test_limit_user", client=self.client)
                program = TestUtils.create_program(
                    program_title="Docker-Image-Program-Test",
                    author="test_limit_user",
                    provider="default",
                )

                # our user will have 2 Jobs, one with `QUEUED` status and other in `SUCCEEDED` status.
                TestUtils.create_job(author=user, status=Job.SUCCEEDED, program=program)
                job = TestUtils.create_job(author=user, status=Job.QUEUED, program=program)
                num_jobs_in_queue = Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()

                # Checking that this test will run according to scripts
                assert self.LIMITS_ACTIVE_JOBS_PER_USER > num_jobs_in_queue

                # filling up the queue to the limit
                for _ in range(num_jobs_in_queue, self.LIMITS_ACTIVE_JOBS_PER_USER):
                    programs_response = run_program()
                    assert programs_response.status_code == status.HTTP_200_OK  # ok

                # the user has a job with status `SUCCEEDED`.
                # Checking it doesn't count it towards the limit
                assert (
                    self.LIMITS_ACTIVE_JOBS_PER_USER
                    == Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()
                )
                assert Job.objects.filter(author=user).count() > self.LIMITS_ACTIVE_JOBS_PER_USER

                # Failing to add a job to the queue
                programs_response_fail = run_program()
                assert programs_response_fail.status_code == status.HTTP_429_TOO_MANY_REQUESTS  # limit error
                assert (
                    programs_response_fail.data.get("message") == f"Active job limit reached. The maximum allowed is "
                    f"{self.LIMITS_ACTIVE_JOBS_PER_USER}."
                )

                # Changing a queued job status to Fail and check we can submit another job.
                job = Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).first()
                job.status = Job.FAILED
                job.save()

                assert (
                    self.LIMITS_ACTIVE_JOBS_PER_USER
                    > Job.objects.filter(author=user, status__in=Job.ACTIVE_STATUSES).count()
                )

                # lastly adding job to the queue
                programs_response = run_program()
                assert programs_response.status_code == status.HTTP_200_OK  # ok

    def test_run_locked(self):
        """Tests run disabled program."""

        user = TestUtils.authorize_client(user="test_user", client=self.client)

        # Create disabled program with custom message
        TestUtils.create_program(
            program_title="ProgramLocked",
            author=user,
            disabled=True,
            disabled_message="Program is locked",
        )

        arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/run/",
            data={
                "title": "ProgramLocked",
                "arguments": arguments,
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": True,
                },
            },
            format="json",
        )

        assert programs_response.status_code == status.HTTP_423_LOCKED
        assert programs_response.data.get("message") == "Program is locked"

        job_events = JobEvent.objects.filter()
        assert len(job_events) == 0

    def test_run_locked_default_msg(self):
        """Tests run disabled program."""

        user = TestUtils.authorize_client(user="test_user", client=self.client)

        # Create disabled program without custom message (uses default)
        TestUtils.create_program(
            program_title="ProgramLocked2",
            author=user,
            disabled=True,
        )

        arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/run/",
            data={
                "title": "ProgramLocked2",
                "arguments": arguments,
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": True,
                },
            },
            format="json",
        )

        assert programs_response.status_code == status.HTTP_423_LOCKED
        assert programs_response.data.get("message") == Program.DEFAULT_DISABLED_MESSAGE

        job_events = JobEvent.objects.filter()
        assert len(job_events) == 0

    def test_upload_private_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        TestUtils.authorize_client(user="test_user_2", client=self.client)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Private function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                },
            )
            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("provider") is None

    def test_upload_custom_image_without_provider(self):
        """Tests upload end-point authorized."""

        TestUtils.authorize_client(user="test_user_2", client=self.client)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "icr.io/awesome-namespace/awesome-title",
            },
        )
        assert programs_response.status_code == status.HTTP_400_BAD_REQUEST

    def test_upload_custom_image_without_access_to_the_provider(self):
        """Tests upload end-point authorized."""

        TestUtils.authorize_client(user="test_user", client=self.client)

        # Create ibm provider (user doesn't have access)
        TestUtils.get_or_create_provider("ibm")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "docker.io/awesome-namespace/awesome-title",
                "provider": "ibm",
            },
        )
        assert programs_response.status_code == status.HTTP_404_NOT_FOUND

        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "ibm/Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "docker.io/awesome-namespace/awesome-title",
            },
        )
        assert programs_response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_provider_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(user="test_user_2", client=self.client)
        # create admin group
        TestUtils.get_or_create_group(group="default-group")
        TestUtils.add_user_to_group(user=user, group="default-group")

        # Create default provider and add user as admin
        TestUtils.get_or_create_provider(provider="default", admin_group="default-group")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Provider Function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                    "provider": "default",
                },
            )
            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("provider") == "default"

    def test_upload_provider_function_with_title(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(user="test_user_2", client=self.client)

        # Create default provider and add user as admin
        TestUtils.get_or_create_provider(provider="default", admin_group="default-group")
        TestUtils.add_user_to_group(user, "default-group")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "default/Provider Function",
                    "entrypoint": "test_user_3_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                },
            )
            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("provider") == "default"
            assert programs_response.data.get("entrypoint") == "test_user_3_program.py"
            assert programs_response.data.get("title") == "Provider Function"

            # Verify that program with full title doesn't exist
            try:
                Program.objects.get(title="default/Provider Function")
                assert False, "Program should not exist with full title"
            except Program.DoesNotExist:
                pass  # Expected

    def test_upload_authorization_error(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        TestUtils.authorize_client(user="test_user", client=self.client)

        # Create default provider (user doesn't have admin access)
        TestUtils.get_or_create_provider("default")

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Provider Function",
                "entrypoint": "test_user_2_program.py",
                "dependencies": "[]",
                "env_vars": env_vars,
                "artifact": fake_file,
                "provider": "default",
            },
        )
        assert programs_response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_provider_function_with_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(user="test_user_2", client=self.client)
        TestUtils.get_or_create_group(group="default-group")
        # Create default provider and add user as admin
        TestUtils.get_or_create_provider(provider="default", admin_group="default-group")
        TestUtils.add_user_to_group(user, "default-group")

        # Create another program to make total count 2
        TestUtils.create_program(
            program_title="Existing Program",
            author=user,
            provider="default",
        )

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        description = "sample function implemented in a custom image"

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Provider Function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "artifact": fake_file,
                    "provider": "default",
                    "description": description,
                },
            )
            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("provider") == "default"

            programs_response = self.client.get(reverse("v1:programs-list"), format="json")

            assert programs_response.status_code == status.HTTP_200_OK
            assert len(programs_response.data) == 2
            found = False
            for resp_data in programs_response.data:
                if resp_data.get("title") == "Provider Function":
                    assert resp_data.get("description") == description
                    found = True
            assert found

    def test_get_by_title(self):
        """Tests get program by title."""
        user = TestUtils.authorize_client(user="test_user_2", client=self.client)

        # Create provider program
        TestUtils.create_program(
            program_title="Docker-Image-Program",
            author=user,
            provider="default",
        )

        # Adding a program `test_user_2` doesn't have access to.
        TestUtils.create_program(
            program_title="Program",
            author="test_user",
        )

        # Trying to get a provider function WITHOUT specifying provider should return 404
        # because get_user_function() correctly filters by provider=None
        programs_response = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            format="json",
        )
        assert programs_response.status_code == status.HTTP_404_NOT_FOUND

        # Getting a provider function WITH provider query param should work
        programs_response_with_provider = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "default"},
            format="json",
        )
        assert programs_response_with_provider.data.get("provider") == "default"
        assert programs_response_with_provider.data.get("title") is not None

        programs_response_non_existing_provider = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "non-existing"},
            format="json",
        )
        assert programs_response_non_existing_provider.status_code == status.HTTP_404_NOT_FOUND

        programs_response_do_not_have_access = self.client.get(
            "/api/v1/programs/get_by_title/Program/",
            {"provider": "non-existing"},
            format="json",
        )
        assert programs_response_do_not_have_access.status_code == status.HTTP_404_NOT_FOUND

    def test_get_jobs(self):
        """Tests run existing authorized."""

        user_1 = TestUtils.authorize_client(user="test_user", client=self.client)
        user_2 = TestUtils.authorize_client(user="test_user_2", client=self.client)

        # create admin group
        TestUtils.get_or_create_group(group="default-group")

        # Create default provider and add `test_user_2` as admin
        TestUtils.get_or_create_provider(provider="default", admin_group="default-group")
        TestUtils.add_user_to_group(user_2, "default-group")

        # Create program w/o provider with authored by test_user
        program_no_provider = TestUtils.create_program(program_title="Program-No-Provider", author=user_1)
        # `test_user_2` run a job with a program authored by `test_user`.
        TestUtils.create_job(author=user_2, program=program_no_provider, status=Job.QUEUED)  # add job with status QUEUE

        # in the fixtures there are 3 jobs with status Succeed, Queued and Running by test_user

        # Create program w/ provider authored by `test_user_2` (which is also in the admin group of the provider).
        program_with_provider = TestUtils.create_program(
            program_title="Program-With-Provider",
            author=user_2,
            provider="default",
        )
        # Add 2 jobs of the program (1 by test_user_2 with succeed status , 1 by test_user with queued status)
        TestUtils.create_job(author=user_1, program=program_with_provider, status=Job.QUEUED)
        TestUtils.create_job(author=user_2, program=program_with_provider, status=Job.SUCCEEDED)

        # program w/o provider response
        response = self.client.get(
            f"/api/v1/programs/{program_no_provider.id}/get_jobs/",
            format="json",
        )
        assert len(response.data) == 1
        assert response.status_code == status.HTTP_200_OK

        # program w/ provider by not author (sees all jobs as program admin)
        response = self.client.get(
            f"/api/v1/programs/{program_with_provider.id}/get_jobs/",
            format="json",
        )
        assert len(response.data) == 2
        assert response.status_code == status.HTTP_200_OK

        # program w/ provider by author (sees only own job)
        TestUtils.authorize_client(user=user_1.username, client=self.client)

        response = self.client.get(
            f"/api/v1/programs/{program_with_provider.id}/get_jobs/",
            format="json",
        )
        assert len(response.data) == 1
        assert response.status_code == status.HTTP_200_OK

    def test_upload_private_function_update_without_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(user="test_user", client=self.client)

        # Create existing program with description
        TestUtils.create_program(
            program_title="Program",
            author=user,
            description="Program description test",
        )

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Program",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "artifact": fake_file,
                },
            )

            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("description") == "Program description test"

    def test_upload_private_function_update_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = TestUtils.authorize_client(user="test_user", client=self.client)
        # Create existing program with description
        TestUtils.create_program(
            program_title="Program",
            author=user,
            description="Program description test",
        )

        new_description = "New program description test"

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Program",
                    "entrypoint": "test_user_2_program.py",
                    "description": new_description,
                    "dependencies": "[]",
                    "artifact": fake_file,
                },
            )

            assert programs_response.status_code == status.HTTP_200_OK
            assert programs_response.data.get("description") == new_description

    def test_run_user_function_with_same_title_as_provider_function(self):
        """
        Tests that when a user has two functions with the same title
        (one without provider and one with provider), running without
        provider correctly uses the user function (provider=None) and
        stores arguments in the correct path.
        """

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = TestUtils.authorize_client(user="test_user_2", client=self.client)
            # create admin group
            TestUtils.get_or_create_group(group="default-group")
            TestUtils.add_user_to_group(user=user, group="default-group")

            # Create user function (without provider)
            fake_file_user = ContentFile(b"print('User Function')")
            fake_file_user.name = "user_func.tar"

            upload_response_user = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "duplicate-title",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file_user,
                },
            )
            assert upload_response_user.status_code == status.HTTP_200_OK
            assert upload_response_user.data.get("provider") is None

            # Create provider function (with provider) - same title, same author
            # set admin-group for upload permission for the provider function.
            TestUtils.get_or_create_provider(provider="default", admin_group="default-group")
            fake_file_provider = ContentFile(b"print('Provider Function')")
            fake_file_provider.name = "provider_func.tar"

            upload_response_provider = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "duplicate-title",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file_provider,
                    "provider": "default",
                },
            )
            assert upload_response_provider.status_code == status.HTTP_200_OK
            assert upload_response_provider.data.get("provider") == "default"

            # Verify both functions exist
            user_program = Program.objects.get(title="duplicate-title", author=user, provider=None)
            provider_program = Program.objects.get(title="duplicate-title", author=user, provider__name="default")
            assert user_program is not None
            assert provider_program is not None
            assert user_program.id != provider_program.id

            # Run the user function (without provider)
            arguments = json.dumps({"test_key": "test_value"})
            run_response = self.client.post(
                "/api/v1/programs/run/",
                data={
                    "title": "duplicate-title",
                    "arguments": arguments,
                    "config": {
                        "workers": None,
                        "min_workers": 1,
                        "max_workers": 5,
                        "auto_scaling": True,
                    },
                },
                format="json",
            )

            assert run_response.status_code == status.HTTP_200_OK
            job_id = run_response.data.get("id")
            job = Job.objects.get(id=job_id)

            # Verify the job is associated with the USER function (not provider function)
            assert job.program.id == user_program.id
            assert job.program.provider is None

            # Verify arguments are stored in the correct path (user storage, not provider)
            arguments_storage = get_arguments_storage(user.username, user_program)
            stored_arguments = arguments_storage.get(job.id)
            assert stored_arguments == arguments

            # Verify the storage path is for user function (no provider in path)
            expected_arguments_path = os.path.join(self.MEDIA_ROOT, user.username, "arguments")
            assert arguments_storage.absolute_path == expected_arguments_path

    def test_program_version_field_returned(self):
        """Tests that the Program `version` field is returned by the API."""
        user = TestUtils.authorize_client(user="test_user_2", client=self.client)

        # create admin group
        TestUtils.get_or_create_group(group="default-group")

        # Create default provider and add `test_user_2` as admin
        TestUtils.get_or_create_provider(provider="default", admin_group="default-group")
        TestUtils.add_user_to_group(user, "default-group")

        # Update fixture program to have a version string
        # Create program w/o provider with authored by test_user
        program = TestUtils.create_program(
            program_title="Docker-Image-Program",
            author=user,
            provider="default",
        )
        program.version = "1.2.3"
        program.save()

        response = self.client.get(
            "/api/v1/programs/get_by_title/Docker-Image-Program/",
            {"provider": "default"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("version") == "1.2.3"

    def test_upload_invalid_version_returns_error(self):
        """Tests upload returns 400 when version is invalid."""

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            TestUtils.authorize_client(user="test_user_2", client=self.client)

            env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
            version = "not_a_version"

            response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Private function",
                    "entrypoint": "test_user_2_program.py",
                    "dependencies": "[]",
                    "env_vars": env_vars,
                    "version": version,
                },
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            # Error message should mention invalid version
            errors = json.dumps(response.data)
            assert "Invalid version" in errors

    def test_upload_with_runner_field(self):
        """Tests that the runner field is persisted on upload."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        TestUtils.authorize_client(user="test_user_2", client=self.client)

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            programs_response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Fleets function",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file,
                    "runner": Program.FLEETS,
                },
            )
            assert programs_response.status_code == status.HTTP_200_OK

        program = Program.objects.get(title="Fleets function")
        assert program.runner == Program.FLEETS

    def test_upload_without_runner_defaults_to_ray(self):
        """Upload without runner field defaults to Program.RAY."""
        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        TestUtils.authorize_client(user="test_user_2", client=self.client)

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            response = self.client.post(
                "/api/v1/programs/upload/",
                data={
                    "title": "Default runner function",
                    "entrypoint": "main.py",
                    "dependencies": "[]",
                    "artifact": fake_file,
                },
            )
            assert response.status_code == status.HTTP_200_OK

        program = Program.objects.get(title="Default runner function")
        assert program.runner == Program.RAY


@pytest.mark.django_db
class TestProgramApiRuntimeInstances:
    """Programs endpoints with runtime instances authorization (use_legacy_authorization=False)."""

    @pytest.fixture
    def client(self):
        return APIClient()

    @pytest.fixture
    def authorize(self, client):
        """Return a callable that authenticates the client with accessible_functions."""
        from api.domain.authentication.channel import Channel

        def _do(username, accessible_functions):
            user, _ = User.objects.get_or_create(username=username)
            token = MagicMock()
            token.accessible_functions = accessible_functions
            token.channel = Channel.LOCAL
            token.token = b"test-token"
            token.instance = None
            client.force_authenticate(user=user, token=token)
            return user

        return _do

    class TestRunProgram:
        @pytest.mark.parametrize(
            "permissions,expected_status",
            [
                ({PLATFORM_PERMISSION_RUN}, status.HTTP_200_OK),
                (set(), status.HTTP_404_NOT_FOUND),
            ],
        )
        def test_run_provider_function(self, client, authorize, permissions, expected_status):
            """run() checks PLATFORM_PERMISSION_RUN in accessible_functions."""
            TestUtils.create_program(program_title="my-func", author="func-author", provider="my-provider")
            authorize("runtime-user", create_function_access_result("my-provider", "my-func", permissions))

            response = client.post(
                "/api/v1/programs/run/",
                data={"title": "my-func", "provider": "my-provider", "arguments": "{}", "config": {"workers": 1}},
                format="json",
            )

            assert response.status_code == expected_status

        @pytest.mark.parametrize(
            "business_model,expected_trial",
            [
                (BusinessModel.TRIAL, True),
                (BusinessModel.SUBSIDIZED, False),
                (BusinessModel.CONSUMPTION, False),
            ],
        )
        def test_run_uses_business_model_from_serverless_client(
            self, client, authorize, business_model, expected_trial
        ):
            """run() propagates business_model from the access entry to the created job."""
            TestUtils.create_program(program_title="my-func", author="func-author", provider="my-provider")
            authorize(
                "runtime-user",
                create_function_access_result(
                    "my-provider", "my-func", {PLATFORM_PERMISSION_RUN}, business_model=business_model
                ),
            )

            response = client.post(
                "/api/v1/programs/run/",
                data={"title": "my-func", "provider": "my-provider", "arguments": "{}", "config": {"workers": 1}},
                format="json",
            )

            assert response.status_code == status.HTTP_200_OK
            job = Job.objects.get(id=response.data["id"])
            assert job.business_model == business_model
            assert job.trial is expected_trial

    class TestList:
        @pytest.mark.parametrize(
            "filter_param,permissions,expected_count",
            [
                ("catalog", {PLATFORM_PERMISSION_READ}, 1),  # only accessible provider func
                ("catalog", set(), 0),  # no access to provider funcs
                ("serverless", {PLATFORM_PERMISSION_READ}, 1),  # own function, permissions irrelevant
                ("serverless", set(), 1),
                (None, {PLATFORM_PERMISSION_READ}, 2),  # own + accessible provider
                (None, set(), 1),  # only own function
            ],
        )
        def test_list(self, client, authorize, filter_param, permissions, expected_count):
            """list() returns different results depending on filter and accessible_functions.

            Each filter uses a different permission to match against accessible_functions:
              - catalog   → PLATFORM_PERMISSION_RUN  (functions the user can execute)
              - serverless → no permission check     (only own functions, ignores accessible_functions)
              - no filter  → PLATFORM_PERMISSION_READ (functions the user can see)
            """
            TestUtils.create_program(program_title="my-user-func", author="runtime-user")
            TestUtils.create_program(program_title="funcA", author="other-author", provider="provA")
            TestUtils.create_program(program_title="funcB", author="other-author", provider="provB")
            authorize("runtime-user", create_function_access_result("provA", "funcA", permissions))

            params = {"filter": filter_param} if filter_param else {}
            response = client.get(reverse("v1:programs-list"), params, format="json")

            assert response.status_code == status.HTTP_200_OK
            assert len(response.data) == expected_count

    class TestUpload:
        @pytest.mark.parametrize(
            "permissions,expected_status",
            [
                ({PLATFORM_PERMISSION_WRITE}, status.HTTP_200_OK),
                (set(), status.HTTP_404_NOT_FOUND),
            ],
        )
        def test_upload_provider_function(self, client, authorize, permissions, expected_status):
            """upload() checks PLATFORM_PERMISSION_WRITE in accessible_functions."""
            TestUtils.get_or_create_provider(provider="my-provider")
            authorize("runtime-user", create_function_access_result("my-provider", "my-func", permissions))

            response = client.post(
                "/api/v1/programs/upload/",
                data={"title": "my-func", "provider": "my-provider", "dependencies": "[]", "entrypoint": "main.py"},
            )

            assert response.status_code == expected_status

    class TestGetByTitle:
        @pytest.mark.parametrize(
            "permissions,expected_status",
            [
                ({PLATFORM_PERMISSION_READ}, status.HTTP_200_OK),
                (set(), status.HTTP_404_NOT_FOUND),
            ],
        )
        def test_get_by_title(self, client, authorize, permissions, expected_status):
            """get_by_title() checks PLATFORM_PERMISSION_READ in accessible_functions."""
            TestUtils.create_program(program_title="my-func", author="func-author", provider="my-provider")
            authorize("runtime-user", create_function_access_result("my-provider", "my-func", permissions))

            response = client.get(
                "/api/v1/programs/get_by_title/my-func/",
                {"provider": "my-provider"},
                format="json",
            )

            assert response.status_code == expected_status

    class TestGetJobs:
        @pytest.mark.parametrize(
            "permissions,expected_job_count",
            [
                ({PLATFORM_PERMISSION_JOBS_READ}, 2),  # provider admin sees all jobs
                (set(), 1),  # regular user sees only own job
            ],
        )
        def test_get_jobs(self, client, authorize, permissions, expected_job_count):
            """get_jobs() checks PLATFORM_PERMISSION_JOBS_READ in accessible_functions."""
            program = TestUtils.create_program(program_title="my-func", author="func-author", provider="my-provider")
            user, _ = User.objects.get_or_create(username="runtime-user")
            other_user, _ = User.objects.get_or_create(username="other-user")
            TestUtils.create_job(author=user, program=program, status=Job.QUEUED)
            TestUtils.create_job(author=other_user, program=program, status=Job.QUEUED)
            authorize("runtime-user", create_function_access_result("my-provider", "my-func", permissions))

            response = client.get(f"/api/v1/programs/{program.id}/get_jobs/", format="json")

            assert response.status_code == status.HTTP_200_OK
            assert len(response.data) == expected_job_count
