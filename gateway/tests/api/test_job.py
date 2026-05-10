"""Tests jobs APIs."""

import json
import os
import re
import shutil
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User, Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from core.services.storage.result_storage import ResultStorage

from core.domain.authorization.function_access_entry import FunctionAccessEntry
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.model_managers.job_events import JobEventContext, JobEventOrigin, JobEventType
from core.models import Job, JobEvent, PLATFORM_PERMISSION_JOBS_READ, Program, Provider, RuntimeJob


@pytest.mark.django_db
class TestJobApi:
    """TestJobApi."""

    _fake_media_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
    )

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        from django.core.management import call_command

        call_command("loaddata", "tests/fixtures/fixtures.json")
        settings.MEDIA_ROOT = str(tmp_path)
        self.client = APIClient()

    def _authorize(self, username, accessible_functions=FunctionAccessResult(use_legacy_authorization=True)):
        """Authorize client and return the user."""
        user, _ = User.objects.get_or_create(username=username)
        token = MagicMock()
        token.accessible_functions = accessible_functions
        self.client.force_authenticate(user=user, token=token)
        return user

    def _create_job(
        self,
        author: str,
        provider_admin: str = None,
    ) -> Job:
        author, _ = User.objects.get_or_create(username=author)
        provider = None

        if provider_admin:
            provider = Provider.objects.create(name=provider_admin)
            admin_group, _ = Group.objects.get_or_create(name=provider_admin)
            admin_user, _ = User.objects.get_or_create(username=provider_admin)
            admin_user.groups.add(admin_group)
            provider.admin_groups.add(admin_group)

        program = Program.objects.create(
            title=f"{author}-{provider_admin or 'custom'}",
            author=author,
            provider=provider,
        )

        job = Job.objects.create(author=author, program=program)
        return job

    def test_job_non_auth_user(self):
        """Tests job list non-authorized."""
        url = reverse("v1:jobs-list")
        response = self.client.get(url, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_job_list(self):
        """Tests job list authorized."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 5
        assert jobs_response.data.get("results")[0].get("status") == "SUCCEEDED"
        assert jobs_response.data.get("results")[0].get("result") is None

    def test_job_catalog_list(self):
        """Tests job list authorized."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"filter": "catalog"}, format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 2
        assert jobs_response.data.get("results")[0].get("status") == "QUEUED"
        assert jobs_response.data.get("results")[0].get("result") is None

    def test_job_serverless_list(self):
        """Tests job list authorized."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"filter": "serverless"}, format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 3

    def test_job_list_filter_status(self):
        """Tests job list filtered by status."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"status": "SUCCEEDED"}, format="json")

        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 1
        assert jobs_response.data.get("results")[0]["status"] == "SUCCEEDED"

    def test_job_list_filter_created_after(self):
        """Tests job list filtered by created_after."""
        self._authorize("test_user")
        created_after = "2023-02-02T00:00:00.000000Z"

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"created_after": created_after}, format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 3
        for job in jobs_response.data.get("results"):
            assert job["created"] > created_after

    def test_job_list_filter_function_name(self):
        """Tests job list filtered by function."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"function": "Docker-Image-Program"}, format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 1

    def test_job_list_filter_pagination(self):
        """Tests job list pagination."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-list"), {"offset": 0, "limit": 2}, format="json")
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 5
        assert len(jobs_response.data.get("results")) == 2
        assert re.search(r"/api/v1/jobs/\?limit=2&offset=2$", jobs_response.data.get("next"))
        assert jobs_response.data.get("previous") is None

    def test_job_provider_list_wrong_params(self):
        """Tests job provider list wrong params."""
        self._authorize("test_user")

        jobs_response = self.client.get(reverse("v1:jobs-provider-list"), {}, format="json")
        assert jobs_response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            jobs_response.content,
            b'{"message":"\'provider\' not provided or is not valid"}',
        )

    def test_job_provider_list_wrong_provider(self):
        """Tests job provider list wrong provider."""
        self._authorize("test_user")

        provider = "fake_provider"
        function = "Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        assert jobs_response.status_code == status.HTTP_404_NOT_FOUND
        assert jobs_response.data.get("message") == f"Provider {provider} doesn't exist."

    def test_job_provider_list_not_authorized_provider(self):
        """Tests job provider list not authorized provider."""
        self._authorize("test_user")
        provider = "default"
        function = "Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        assert jobs_response.status_code == status.HTTP_404_NOT_FOUND
        assert jobs_response.data.get("message") == f"Provider {provider} doesn't exist."

    def test_job_provider_list_function_not_found(self):
        """Tests job provider list not authorized provider."""
        self._authorize("test_user_2")
        provider = "default"
        function = "fake_program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        assert jobs_response.status_code == status.HTTP_404_NOT_FOUND
        assert jobs_response.data.get("message") == f"Qiskit Function {provider}/{function} doesn't exist."

    def test_job_provider_list_ok(self):
        """Tests job provider list without errors."""
        self._authorize("test_user_2")
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )

        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 2

    def test_job_provider_list_filter_status(self):
        """Tests job provider list filtered by status."""
        self._authorize("test_user_2")
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function, "status": "SUCCEEDED"},
            format="json",
        )

        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 1
        assert jobs_response.data.get("results")[0]["status"] == "SUCCEEDED"

    def test_job_provider_list_created_after(self):
        """Tests job provider list filtered by created_after."""
        self._authorize("test_user_2")
        provider = "default"
        function = "Docker-Image-Program"
        created_after = "2023-02-02"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {
                "provider": provider,
                "function": function,
                "created_after": created_after,
            },
            format="json",
        )

        created_response = jobs_response.data.get("results")[0]["created"]
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 1
        assert created_response > created_after

    def test_job_provider_list_pagination(self):
        """Tests job provider list pagination."""
        self._authorize("test_user_2")
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function, "limit": 1, "offset": 1},
            format="json",
        )

        assert jobs_response.status_code == status.HTTP_200_OK
        assert len(jobs_response.data.get("results")) == 1
        assert jobs_response.data.get("next") is None
        assert re.search(
            r"/api/v1/jobs/provider/\?limit=1&offset=0$",
            jobs_response.data.get("previous"),
        )

    def test_job_provider_list_runtime_instances_ok(self):
        """Runtime instances path: accessible_functions has provider+function with PROVIDER_JOBS 200."""
        entry = FunctionAccessEntry(
            provider_name="default",
            function_title="Docker-Image-Program",
            permissions={PLATFORM_PERMISSION_JOBS_READ},
            business_model=BusinessModel.SUBSIDIZED,
        )
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[entry])
        self._authorize("test_user", accessible_functions=accessible)

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": "default"},
            format="json",
        )

        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("count") == 2

    def test_job_provider_list_runtime_instances_no_access(self):
        """Runtime instances path: accessible_functions has no PROVIDER_JOBS for the provider → 404."""
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
        self._authorize("test_user", accessible_functions=accessible)

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": "default"},
            format="json",
        )

        assert jobs_response.status_code == status.HTTP_404_NOT_FOUND
        assert jobs_response.data.get("message") == "Provider default doesn't exist."

    def test_job_save_result(self, settings):
        """Tests job results save."""
        self._authorize("test_user")
        job_id = "57fc2e4d-267f-40c6-91a3-38153272e764"
        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=[job_id]),
            format="json",
            data={"result": json.dumps({"ultimate": 42})},
        )
        result_path = os.path.join(settings.MEDIA_ROOT, "test_user", "results", f"{job_id}.json")
        assert os.path.exists(result_path)
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("result") == '{"ultimate": 42}'

    def test_not_authorized_job_save_result(self):
        """Tests job results save."""
        self._authorize("test_user")
        job_id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec84"
        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=[job_id]),
            format="json",
            data={"result": json.dumps({"ultimate": 42})},
        )

        assert jobs_response.status_code == status.HTTP_404_NOT_FOUND
        assert jobs_response.data.get("message") == f"Job [{job_id}] not found"

    def test_job_save_result_uses_author_username(self):
        """
        Tests that job results are saved using job.author.username,
        not the requesting user's username. This ensures results are written
        to the correct storage path where they can be retrieved later.

        Note: Currently can_save_result() only allows authors to save results,
        but this test validates the correct behavior if permissions change in
        the future to allow other users (e.g., system processes) to save results.
        """
        # Get a job created by test_user (author=1)
        job = Job.objects.get(pk="57fc2e4d-267f-40c6-91a3-38153272e764")
        assert job.author.username == "test_user"

        # Save result as the author
        self._authorize("test_user")
        test_result = json.dumps({"test_save": "value"})
        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=[str(job.id)]),
            format="json",
            data={"result": test_result},
        )
        assert jobs_response.status_code == status.HTTP_200_OK

        # Verify result is saved in author's directory
        result_storage = ResultStorage(job.author.username)
        saved_result = result_storage.get(str(job.id))
        assert saved_result == test_result

        # If we incorrectly saved using a different user's username, we wouldn't find it there
        different_user = User.objects.get(username="test_user_2")
        wrong_result_storage = ResultStorage(different_user.username)
        wrong_result = wrong_result_storage.get(str(job.id))
        assert wrong_result is None  # Should not find result in wrong path

    def test_job_arguments_storage_path_user(self, settings):
        """
        Tests that job arguments for user functions (no provider) are saved to:
        /data/{username}/arguments/

        This validates the DATA_PATH environment variable computation in build_env_variables()
        for user functions.
        """
        from core.services.storage.arguments_storage import ArgumentsStorage

        # Create user function (no provider)
        user_job = self._create_job(author="test_user")
        assert user_job.program.provider is None

        # Save arguments for user function
        user_args_storage = ArgumentsStorage(username=user_job.author.username, function=user_job.program)
        test_args = '{"param": "value"}'
        user_args_storage.save(str(user_job.id), test_args)

        # Verify arguments saved in user's directory
        expected_user_path = os.path.join(settings.MEDIA_ROOT, "test_user", "arguments", f"{user_job.id}.json")
        assert os.path.exists(expected_user_path)

        # Verify we can retrieve the arguments
        retrieved_args = user_args_storage.get(str(user_job.id))
        assert retrieved_args == test_args

        # Verify arguments are NOT in provider path
        fake_program = MagicMock()
        fake_program.title = user_job.program.title
        fake_program.provider = MagicMock()
        fake_program.provider.name = "fake_provider"
        wrong_provider_storage = ArgumentsStorage(username=user_job.author.username, function=fake_program)
        assert wrong_provider_storage.get(str(user_job.id)) is None

    def test_job_arguments_storage_path_provider(self, settings):
        """
        Tests that job arguments for provider functions are saved to:
        /data/{username}/{provider}/{function}/arguments/

        This validates the DATA_PATH environment variable computation in build_env_variables()
        for provider functions.
        """
        from core.services.storage.arguments_storage import ArgumentsStorage

        # Create provider function
        provider_job = self._create_job(author="test_user", provider_admin="test_provider")
        assert provider_job.program.provider is not None
        assert provider_job.program.provider.name == "test_provider"

        # Save arguments for provider function
        provider_args_storage = ArgumentsStorage(
            username=provider_job.author.username,
            function=provider_job.program,
        )
        provider_test_args = '{"provider_param": "provider_value"}'
        provider_args_storage.save(str(provider_job.id), provider_test_args)

        # Verify arguments saved in provider's directory structure
        expected_provider_path = os.path.join(
            settings.MEDIA_ROOT,
            "test_user",
            "test_provider",
            provider_job.program.title,
            "arguments",
            f"{provider_job.id}.json",
        )
        assert os.path.exists(expected_provider_path)

        # Verify we can retrieve the arguments
        retrieved_provider_args = provider_args_storage.get(str(provider_job.id))
        assert retrieved_provider_args == provider_test_args

        # Verify provider function arguments are NOT in user-only path
        no_provider_program = MagicMock()
        no_provider_program.title = provider_job.program.title
        no_provider_program.provider = None
        wrong_user_storage = ArgumentsStorage(username=provider_job.author.username, function=no_provider_program)
        assert wrong_user_storage.get(str(provider_job.id)) is None

    def test_job_update_sub_status(self):
        """Test job update sub status"""
        self._authorize("test_user")
        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        assert response_sub_status.status_code == status.HTTP_200_OK
        job = response_sub_status.data.get("job")
        assert job.get("status") == "RUNNING"
        assert job.get("sub_status") == "MAPPING"

        job_events = JobEvent.objects.filter(job=job_id)
        assert len(job_events) == 1
        assert job_events[0].event_type == JobEventType.SUB_STATUS_CHANGE
        assert job_events[0].data["sub_status"] == Job.MAPPING
        assert job_events[0].origin == JobEventOrigin.API
        assert job_events[0].context == JobEventContext.SET_SUB_STATUS

    def test_job_update_sub_status_wrong_value(self):
        """Test job update sub status with wrong sub-status value"""
        self._authorize("test_user")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "JUMPING"},
        )

        assert response_sub_status.status_code == status.HTTP_400_BAD_REQUEST
        assert response_sub_status.data.get("message") == "'sub_status' not provided or is not valid"

        job_events = JobEvent.objects.filter(job=job_id)
        assert len(job_events) == 0

    def test_job_update_sub_status_empty_value(self):
        """Test job update sub status with empty sub-status"""
        self._authorize("test_user")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(reverse("v1:jobs-sub-status", args=[job_id]), format="json")

        assert response_sub_status.status_code == status.HTTP_400_BAD_REQUEST
        assert response_sub_status.data.get("message") == "'sub_status' not provided or is not valid"

        job_events = JobEvent.objects.filter(job=job_id)
        assert len(job_events) == 0

    def test_job_update_sub_status_wrong_user(self):
        """Test job update sub status with unauthorized user"""
        self._authorize("test_user_2")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        assert response_sub_status.status_code == status.HTTP_404_NOT_FOUND
        assert response_sub_status.data.get("message") == f"Job [{job_id}] not found"

        job_events = JobEvent.objects.filter(job=job_id)
        assert len(job_events) == 0

    def test_job_update_sub_status_not_running(self):
        """Test job update sub status not in running state"""
        self._authorize("test_user")

        job_id = "57fc2e4d-267f-40c6-91a3-38153272e764"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        assert response_sub_status.status_code == status.HTTP_403_FORBIDDEN
        assert (
            response_sub_status.data.get("message")
            == "Cannot update 'sub_status' when is not in active status. (Currently SUCCEEDED)"
        )

        job_events = JobEvent.objects.filter(job=job_id)
        assert len(job_events) == 0

    def test_user_has_access_to_job_result_from_provider_function(self):
        """
        User has access to job result from a function provider
        as the authot of the job
        """
        self._authorize("test_user")

        jobs_response = self.client.get(
            reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec87"]),
            format="json",
        )
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("result") == '{"somekey":1}'

    def test_provider_admin_has_no_access_to_job_result_from_provider_function(self):
        """
        A provider admin has no access to job result from a function provider
        if it's not the author of the job
        """
        self._authorize("test_user_3")

        jobs_response = self.client.get(
            reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec87"]),
            format="json",
        )
        assert jobs_response.status_code == status.HTTP_200_OK
        assert jobs_response.data.get("result") is None

    def test_stop_job(self):
        """Tests job stop."""
        self._authorize("test_user")

        job_stop_response = self.client.post(
            reverse(
                "v1:jobs-stop",
                args=["8317718f-5c0d-4fb6-9947-72e480b8a348"],
            ),
            format="json",
        )
        assert job_stop_response.status_code == status.HTTP_200_OK
        job = Job.objects.filter(id__exact="8317718f-5c0d-4fb6-9947-72e480b8a348").first()
        assert job.status == Job.STOPPED
        assert "Job has been stopped." in job_stop_response.data.get("message")

        job_events = JobEvent.objects.filter(job=job)
        assert len(job_events) == 1
        assert job_events[0].event_type == JobEventType.STATUS_CHANGE
        assert job_events[0].data["status"] == Job.STOPPED
        assert job_events[0].origin == JobEventOrigin.API
        assert job_events[0].context == JobEventContext.STOP_JOB

    def test_runtime_jobs_post(self):
        """Tests runtime jobs POST endpoint."""
        self._authorize("test_user")

        # Job with a single runtime job
        job_id = "8317718f-5c0d-4fb6-9947-72e480b8a348"
        response = self.client.post(
            reverse("v1:jobs-runtime-jobs", args=[job_id]),
            data={
                "runtime_job": "runtime_job_new",
                "runtime_session": "session_id_new",
            },
            format="json",
        )

        expected_message = f"RuntimeJob object [runtime_job_new] " f"created for serverless job id [{job_id}]."

        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("message") == expected_message

        runtime_job = RuntimeJob.objects.get(runtime_job="runtime_job_new")

        assert str(runtime_job.job.id) == "8317718f-5c0d-4fb6-9947-72e480b8a348"
        assert runtime_job.runtime_session == "session_id_new"

    def test_runtime_jobs_get(self):
        """Tests list runtime jobs GET endpoint."""
        self._authorize("test_user")

        # Job with multiple runtime jobs
        response = self.client.get(
            reverse("v1:jobs-runtime-jobs", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        runtime_jobs = response.data["runtime_jobs"]
        assert len(runtime_jobs) == 2
        expected = [
            {"runtime_job": "runtime_job_1", "runtime_session": "session_id_1"},
            {"runtime_job": "runtime_job_2", "runtime_session": "session_id_2"},
        ]
        for job in runtime_jobs:
            assert job in expected

        # Job with a single runtime job
        response = self.client.get(
            reverse("v1:jobs-runtime-jobs", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        runtime_jobs = response.data["runtime_jobs"]
        assert len(runtime_jobs) == 1
        runtime_job = runtime_jobs[0]
        assert runtime_job.get("runtime_job") == "runtime_job_3"
        assert runtime_job.get("runtime_session") == "session_id_3"

        # Job with no runtime jobs
        response = self.client.get(
            reverse(
                "v1:jobs-runtime-jobs",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec86"],
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        runtime_jobs = response.data["runtime_jobs"]
        assert runtime_jobs == []

    def test_stop_job_non_author_gets_404(self):
        """Non-author cannot stop another user's job."""
        self._authorize("test_user_2")

        response = self.client.post(
            reverse("v1:jobs-stop", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        job = Job.objects.filter(id__exact="8317718f-5c0d-4fb6-9947-72e480b8a348").first()
        assert job.status != Job.STOPPED

    def test_job_list_internal_server_error(self):
        """Tests that unexpected exceptions return 500 with proper message."""
        self._authorize("test_user")

        with patch(
            "api.use_cases.jobs.get_runtime_jobs.GetRuntimeJobsUseCase.execute",
            side_effect=Exception("Database connection failed"),
        ):
            response = self.client.get(
                reverse(
                    "v1:jobs-runtime-jobs",
                    args=["57fc2e4d-267f-40c6-91a3-38153272e764"],
                ),
                format="json",
            )

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert response.data.get("message") == "Internal server error"

    def test_job_list_error(self):
        """Tests that unexpected exceptions return 500 with proper message."""
        self._authorize("test_user")

        with patch(
            "api.use_cases.jobs.list.JobsListUseCase.execute",
            side_effect=Exception("Database connection failed"),
        ):
            response = self.client.get(reverse("v1:jobs-list"), format="json")

            assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert response.data.get("message") == "Internal server error"

    def test_runtime_jobs_post_non_author_gets_404(self):
        """Non-author cannot associate runtime jobs to another user's job."""
        self._authorize("test_user_2")

        response = self.client.post(
            reverse("v1:jobs-runtime-jobs", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
            data={"runtime_job": "some_runtime_job"},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_runtime_jobs_get_non_author_gets_404(self):
        """Non-author cannot read runtime jobs of another user's job."""
        self._authorize("test_user_2")

        response = self.client.get(
            reverse("v1:jobs-runtime-jobs", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_job_event_creation(self):
        """Tests create event with all fields."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        code = "1111"
        message = "My test message"
        exception = "ServerlessException"
        args = json.dumps({"ultimate": 42})
        job_event_response = self.client.post(
            reverse(
                "v1:jobs-create-event",
                args=[job_id],
            ),
            format="json",
            data={"type": JobEventType.ERROR, "exception": exception, "code": code, "message": message, "args": args},
        )

        assert job_event_response.status_code == status.HTTP_200_OK
        job_events = JobEvent.objects.filter(job_id=job_id)

        assert len(job_events) == 1
        assert job_events[0].event_type == JobEventType.ERROR
        assert job_events[0].origin == JobEventOrigin.API
        assert job_events[0].context == JobEventContext.SEND_ERROR
        assert job_events[0].data["code"] == code
        assert job_events[0].data["message"] == message
        assert job_events[0].data["exception"] == exception
        assert job_events[0].data["args"] == args

    def test_job_event_creation_non_running(self):
        """Tests create event on a non running job."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.FAILED
        user_job.save()

        job_id = user_job.pk
        code = "1111"
        message = "My test message"
        exception = "ServerlessException"
        args = json.dumps({"ultimate": 42})
        job_event_response = self.client.post(
            reverse(
                "v1:jobs-create-event",
                args=[job_id],
            ),
            format="json",
            data={"type": JobEventType.ERROR, "exception": exception, "code": code, "message": message, "args": args},
        )

        assert job_event_response.status_code == status.HTTP_403_FORBIDDEN
        job_events = JobEvent.objects.filter(job_id=job_id)

        assert len(job_events) == 0

    def test_job_event_without_args(self):
        """Tests create event without args field."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        code = "1111"
        message = "My test message"
        exception = "ServerlessException"
        job_event_response = self.client.post(
            reverse(
                "v1:jobs-create-event",
                args=[job_id],
            ),
            format="json",
            data={"type": JobEventType.ERROR, "exception": exception, "code": code, "message": message},
        )

        assert job_event_response.status_code == status.HTTP_200_OK
        job_events = JobEvent.objects.filter(job_id=job_id)

        assert len(job_events) == 1
        assert job_events[0].event_type == JobEventType.ERROR
        assert job_events[0].origin == JobEventOrigin.API
        assert job_events[0].context == JobEventContext.SEND_ERROR
        assert job_events[0].data["code"] == code
        assert job_events[0].data["message"] == message
        assert job_events[0].data["exception"] == exception
        assert job_events[0].data["args"] == None

    def test_job_event_unauthorized(self):
        """Tests create event with a not authorized user."""

        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()
        self._authorize("test_user_2")

        job_id = user_job.pk
        code = "1111"
        message = "My test message"
        exception = "ServerlessException"
        args = json.dumps({"ultimate": 42})
        job_event_response = self.client.post(
            reverse(
                "v1:jobs-create-event",
                args=[job_id],
            ),
            format="json",
            data={"type": JobEventType.ERROR, "exception": exception, "code": code, "message": message, "args": args},
        )

        assert job_event_response.status_code == status.HTTP_404_NOT_FOUND
        job_events = JobEvent.objects.filter(job_id=job_id)

        assert len(job_events) == 0

    def test_job_event_type_wrong(self):
        """Tests create event using a not valid type."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        code = "1111"
        message = "My test message"
        args = json.dumps({"ultimate": 42})
        job_event_response = self.client.post(
            reverse(
                "v1:jobs-create-event",
                args=[job_id],
            ),
            format="json",
            data={"type": JobEventType.STATUS_CHANGE, "code": code, "message": message, "args": args},
        )

        assert job_event_response.status_code == status.HTTP_400_BAD_REQUEST
        job_events = JobEvent.objects.filter(job_id=job_id)

        assert len(job_events) == 0

    def test_job_events(self):
        """Tests list error events."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        code = "1111"
        code_2 = "1112"
        message = "My test message"
        message_2 = "My test message 2"
        exception = "ServerlessError"
        exception_2 = "CustomError"
        args = {"ultimate": 42}
        args_2 = {"ultimate": 422}
        JobEvent.objects.add_error_event(
            job_id, JobEventOrigin.API, JobEventContext.SEND_ERROR, code, message, exception, args
        )
        JobEvent.objects.add_error_event(
            job_id, JobEventOrigin.API, JobEventContext.SEND_ERROR, code_2, message_2, exception_2, args_2
        )
        JobEvent.objects.add_status_event(
            job_id, JobEventOrigin.SCHEDULER, JobEventContext.SCHEDULE_JOBS, Job.SUCCEEDED
        )

        job_event_response = self.client.get(
            reverse(
                "v1:jobs-get-events",
                args=[job_id],
            ),
            {"type": JobEventType.ERROR},
            format="json",
        )

        assert job_event_response.status_code == status.HTTP_200_OK

        assert len(job_event_response.data) == 2
        event_0 = job_event_response.data[1]
        event_1 = job_event_response.data[0]

        assert event_0["event_type"] == JobEventType.ERROR
        assert event_1["event_type"] == JobEventType.ERROR

        assert event_0["data"]["code"] == code
        assert event_1["data"]["code"] == code_2

        assert event_0["data"]["message"] == message
        assert event_1["data"]["message"] == message_2

        assert event_0["data"]["exception"] == exception
        assert event_1["data"]["exception"] == exception_2

        assert event_0["data"]["args"] == args
        assert event_1["data"]["args"] == args_2

    def test_job_events_wrong_type(self):
        """Tests try to access job events using a wrong type to filter."""

        self._authorize("test_user")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        job_event_response = self.client.get(
            reverse(
                "v1:jobs-get-events",
                args=[job_id],
            ),
            {"type": "NonExistingJobEventType"},
            format="json",
        )

        assert job_event_response.status_code == status.HTTP_400_BAD_REQUEST

    def test_job_events_wrong_user(self):
        """Tests try to access job events from a not authorized user."""

        self._authorize("test_user_2")
        user_job = self._create_job(author="test_user")
        user_job.status = Job.RUNNING
        user_job.save()

        job_id = user_job.pk
        job_event_response = self.client.get(
            reverse(
                "v1:jobs-get-events",
                args=[job_id],
            ),
            {"type": JobEventType.ERROR},
            format="json",
        )
        assert job_event_response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestRetrieveJob:
    """Tests for the v1:retrieve endpoint grouped by authorization path."""

    _fake_media_path = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "resources", "fake_media")
    )

    @pytest.fixture(autouse=True)
    def _load_fixtures(self, tmp_path, settings):
        from django.core.management import call_command

        call_command("loaddata", "tests/fixtures/fixtures.json")
        settings.MEDIA_ROOT = str(tmp_path)

    @pytest.fixture()
    def authorize(self):
        """Returns a callable that authenticates an APIClient and returns it."""
        client = APIClient()

        def _authorize(username, accessible_functions=FunctionAccessResult(use_legacy_authorization=True)):
            user, _ = User.objects.get_or_create(username=username)
            token = MagicMock()
            token.accessible_functions = accessible_functions
            client.force_authenticate(user=user, token=token)
            return client

        return _authorize

    def test_author_retrieves_with_result(self, authorize, settings):
        """Job author can retrieve their own job including the result."""
        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)
        client = authorize("test_user")

        response = client.get(reverse("v1:retrieve", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]), format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("result") == '{"ultimate": 42}'
        assert response.data.get("business_model") == BusinessModel.SUBSIDIZED

    def test_author_retrieves_without_result_param(self, authorize):
        """?with_result=false returns the job without the result field."""
        client = authorize("test_user")

        response = client.get(
            reverse("v1:retrieve", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]) + "?with_result=false",
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("result") is None
        assert response.data.get("business_model") == BusinessModel.SUBSIDIZED

    def test_author_retrieves_inline_result(self, authorize):
        """Author retrieves a job whose result is stored inline in the DB."""
        client = authorize("test_user")

        response = client.get(reverse("v1:retrieve", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]), format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get("result") == '{"somekey":1}'

    def test_result_read_from_authors_storage(self, settings):
        """Result is read from the job author's storage path, not the requesting user's."""
        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        job = Job.objects.get(pk="8317718f-5c0d-4fb6-9947-72e480b8a348")
        assert job.author.username == "test_user"

        result_storage = ResultStorage(job.author.username)
        assert result_storage.get(str(job.id)) is not None

        different_user = User.objects.get(username="test_user_2")
        wrong_result_storage = ResultStorage(different_user.username)
        assert wrong_result_storage.get(str(job.id)) is None

    class TestLegacyGroups:
        def test_provider_admin_can_retrieve(self, authorize):
            """Provider admin (via Django groups) can retrieve a provider job they don't own."""
            # job_author != requester: admin accesses a job created by a different user
            job_author = User.objects.create_user(username="job_author_legacy")
            requester = User.objects.get(username="test_user_2")  # belongs to default-group (admin)
            provider = Provider.objects.get(name="default")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            job = Job.objects.create(author=job_author, program=program, status=Job.QUEUED)

            client = authorize("test_user_2")
            response = client.get(reverse("v1:retrieve", args=[job.id]), format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data.get("status") == "QUEUED"

        def test_non_admin_cannot_retrieve(self, authorize):
            """User not in any admin group cannot retrieve a provider job they don't own."""
            # job_author != requester: test_user is not in default-group
            job_author = User.objects.create_user(username="job_author_non_admin")
            provider = Provider.objects.get(name="default")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            job = Job.objects.create(author=job_author, program=program, status=Job.QUEUED)

            client = authorize("test_user")  # not in default-group
            response = client.get(reverse("v1:retrieve", args=[job.id]), format="json")
            assert response.status_code == status.HTTP_404_NOT_FOUND

    class TestRuntimeInstances:
        def test_jobs_read_permission_grants_access(self, authorize):
            """PLATFORM_PERMISSION_JOBS_READ grants retrieve access to a job the requester doesn't own."""
            # job_author != requester: test_user has JOBS_READ for the function but is not the author
            job_author = User.objects.create_user(username="job_author_rt_ok")
            provider = Provider.objects.get(name="default")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            job = Job.objects.create(author=job_author, program=program, status=Job.QUEUED)

            entry = FunctionAccessEntry(
                provider_name="default",
                function_title="fn",
                permissions={PLATFORM_PERMISSION_JOBS_READ},
                business_model=BusinessModel.SUBSIDIZED,
            )
            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[entry])
            client = authorize("test_user", accessible_functions=accessible)

            response = client.get(reverse("v1:retrieve", args=[job.id]), format="json")
            assert response.status_code == status.HTTP_200_OK
            assert response.data.get("status") == "QUEUED"

        def test_no_permission_denies_access(self, authorize):
            """No PLATFORM_PERMISSION_JOBS_READ → 404 for a job the requester doesn't own."""
            # job_author != requester: test_user has no permissions for the function
            job_author = User.objects.create_user(username="job_author_rt_deny")
            provider = Provider.objects.get(name="default")
            program = Program.objects.create(title="fn", author=job_author, provider=provider)
            job = Job.objects.create(author=job_author, program=program, status=Job.QUEUED)

            accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])
            client = authorize("test_user", accessible_functions=accessible)

            response = client.get(reverse("v1:retrieve", args=[job.id]), format="json")
            assert response.status_code == status.HTTP_404_NOT_FOUND
