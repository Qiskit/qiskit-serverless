"""Tests jobs APIs."""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import models
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Job, RuntimeJob


class TestJobApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    _fake_media_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
    )

    def setUp(self):
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name
        print(self.MEDIA_ROOT)

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

    def _authorize(self, username="test_user"):
        """Authorize client."""
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)

    def test_job_non_auth_user(self):
        """Tests job list non-authorized."""
        url = reverse("v1:jobs-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_job_list(self):
        """Tests job list authorized."""
        self._authorize()

        jobs_response = self.client.get(reverse("v1:jobs-list"), format="json")
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 5)
        self.assertEqual(
            jobs_response.data.get("results")[0].get("status"), "SUCCEEDED"
        )
        self.assertEqual(jobs_response.data.get("results")[0].get("result"), None)

    def test_job_catalog_list(self):
        """Tests job list authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"filter": "catalog"}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 2)
        self.assertEqual(jobs_response.data.get("results")[0].get("status"), "QUEUED")
        self.assertEqual(jobs_response.data.get("results")[0].get("result"), None)

    def test_job_serverless_list(self):
        """Tests job list authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"filter": "serverless"}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 3)

    def test_job_list_filter_status(self):
        """Tests job list filtered by status."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"status": "SUCCEEDED"}, format="json"
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 1)
        self.assertEqual(jobs_response.data.get("results")[0]["status"], "SUCCEEDED")

    def test_job_list_filter_created_after(self):
        """Tests job list filtered by created_after."""
        self._authorize()
        created_after = "2023-02-02T00:00:00.000000Z"

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"created_after": created_after}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 3)
        for job in jobs_response.data.get("results"):
            self.assertGreater(job["created"], created_after)

    def test_job_list_filter_function_name(self):
        """Tests job list filtered by function."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"function": "Docker-Image-Program"}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 1)

    def test_job_list_filter_pagination(self):
        """Tests job list pagination."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"offset": 0, "limit": 2}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 5)
        self.assertEqual(len(jobs_response.data.get("results")), 2)
        self.assertRegex(
            jobs_response.data.get("next"), r"/api/v1/jobs/\?limit=2&offset=2$"
        )
        self.assertEqual(jobs_response.data.get("previous"), None)

    def test_job_provider_list_wrong_params(self):
        """Tests job provider list wrong params."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"), {}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            jobs_response.content,
            b'{"message":"\'provider\' not provided or is not valid"}',
        )

    def test_job_provider_list_wrong_provider(self):
        """Tests job provider list wrong provider."""
        self._authorize()

        provider = "fake_provider"
        function = "Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            jobs_response.data.get("message"), f"Provider {provider} doesn't exist."
        )

    def test_job_provider_list_not_authorized_provider(self):
        """Tests job provider list not authorized provider."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        provider = "default"
        function = "Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            jobs_response.data.get("message"), f"Provider {provider} doesn't exist."
        )

    def test_job_provider_list_function_not_found(self):
        """Tests job provider list not authorized provider."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        provider = "default"
        function = "fake_program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            jobs_response.data.get("message"),
            f"Qiskit Function {provider}/{function} doesn't exist.",
        )

    def test_job_provider_list_ok(self):
        """Tests job provider list without errors."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function},
            format="json",
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 2)

    def test_job_provider_list_filter_status(self):
        """Tests job provider list filtered by status."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function, "status": "SUCCEEDED"},
            format="json",
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 1)
        self.assertEqual(jobs_response.data.get("results")[0]["status"], "SUCCEEDED")

    def test_job_provider_list_created_after(self):
        """Tests job provider list filtered by created_after."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
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
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 1)
        self.assertGreater(created_response, created_after)

    def test_job_provider_list_pagination(self):
        """Tests job provider list pagination."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        provider = "default"
        function = "Docker-Image-Program"

        jobs_response = self.client.get(
            reverse("v1:jobs-provider-list"),
            {"provider": provider, "function": function, "limit": 1, "offset": 1},
            format="json",
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(jobs_response.data.get("results")), 1)
        self.assertEqual(jobs_response.data.get("next"), None)
        self.assertRegex(
            jobs_response.data.get("previous"),
            r"/api/v1/jobs/provider/\?limit=1&offset=0$",
        )

    def test_job_detail(self):
        """Tests job detail authorized."""

        shutil.copytree(self._fake_media_path, self.MEDIA_ROOT, dirs_exist_ok=True)
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"ultimate": 42}')

    def test_job_detail_without_result_param(self):
        """Tests job detail authorized."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"])
                + "?with_result=false",
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), None)

    def test_job_detail_without_result_file(self):
        """Tests job detail authorized."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"somekey":1}')

    def test_job_provider_detail(self):
        """Tests job detail authorized."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        jobs_response = self.client.get(
            reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec86"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("status"), "QUEUED")
        self.assertEqual(jobs_response.data.get("result"), None)

    def test_not_authorized_job_detail(self):
        """Tests job detail fails trying to access to other user job."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec84"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_job_result_uses_author_username(self):
        """
        Tests that job results are retrieved using job.author.username,
        not the requesting user's username. This ensures results are read
        from the correct storage path where they were saved.

        Note: Currently can_read_result() only allows authors to read results,
        but this test validates the correct behavior if permissions change in
        the future to allow provider admins to read results.
        """
        from api.services.storage.result_storage import ResultStorage

        shutil.copytree(self._fake_media_path, self.MEDIA_ROOT, dirs_exist_ok=True)

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            # Get a job created by test_user (author=1)
            job = Job.objects.get(pk="8317718f-5c0d-4fb6-9947-72e480b8a348")
            self.assertEqual(job.author.username, "test_user")

            # Verify results file exists in author's directory
            result_storage = ResultStorage(job.author.username)
            result = result_storage.get(str(job.id))
            self.assertIsNotNone(result)

            # If we incorrectly used a different user's username, we wouldn't find it
            different_user = models.User.objects.get(username="test_user_2")
            wrong_result_storage = ResultStorage(different_user.username)
            wrong_result = wrong_result_storage.get(str(job.id))
            self.assertIsNone(wrong_result)  # Should not find result in wrong path

    def test_job_save_result(self):
        """Tests job results save."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()
            job_id = "57fc2e4d-267f-40c6-91a3-38153272e764"
            jobs_response = self.client.post(
                reverse("v1:jobs-result", args=[job_id]),
                format="json",
                data={"result": json.dumps({"ultimate": 42})},
            )
            result_path = os.path.join(
                self.MEDIA_ROOT, "test_user", "results", f"{job_id}.json"
            )
            self.assertTrue(os.path.exists(result_path))
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"ultimate": 42}')

    def test_not_authorized_job_save_result(self):
        """Tests job results save."""
        self._authorize()
        job_id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec84"
        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=[job_id]),
            format="json",
            data={"result": json.dumps({"ultimate": 42})},
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            jobs_response.data.get("message"),
            f"Job [{job_id}] not found",
        )

    def test_job_save_result_uses_author_username(self):
        """
        Tests that job results are saved using job.author.username,
        not the requesting user's username. This ensures results are written
        to the correct storage path where they can be retrieved later.

        Note: Currently can_save_result() only allows authors to save results,
        but this test validates the correct behavior if permissions change in
        the future to allow other users (e.g., system processes) to save results.
        """
        from api.services.storage.result_storage import ResultStorage

        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            # Get a job created by test_user (author=1)
            job = Job.objects.get(pk="57fc2e4d-267f-40c6-91a3-38153272e764")
            self.assertEqual(job.author.username, "test_user")

            # Save result as the author
            self._authorize()
            test_result = json.dumps({"test_save": "value"})
            jobs_response = self.client.post(
                reverse("v1:jobs-result", args=[str(job.id)]),
                format="json",
                data={"result": test_result},
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)

            # Verify result is saved in author's directory
            result_storage = ResultStorage(job.author.username)
            saved_result = result_storage.get(str(job.id))
            self.assertEqual(saved_result, test_result)

            # If we incorrectly saved using a different user's username, we wouldn't find it there
            different_user = models.User.objects.get(username="test_user_2")
            wrong_result_storage = ResultStorage(different_user.username)
            wrong_result = wrong_result_storage.get(str(job.id))
            self.assertIsNone(wrong_result)  # Should not find result in wrong path

            # Cleanup
            result_path = os.path.join(
                self.MEDIA_ROOT, job.author.username, "results", f"{job.id}.json"
            )
            if os.path.exists(result_path):
                os.remove(result_path)

    def test_job_update_sub_status(self):
        """Test job update sub status"""
        self._authorize()
        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        self.assertEqual(response_sub_status.status_code, status.HTTP_200_OK)
        job = response_sub_status.data.get("job")
        self.assertEqual(job.get("status"), "RUNNING")
        self.assertEqual(job.get("sub_status"), "MAPPING")

    def test_job_update_sub_status_wrong_value(self):
        """Test job update sub status with wrong sub-status value"""
        self._authorize()

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "JUMPING"},
        )

        self.assertEqual(response_sub_status.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_sub_status.data.get("message"),
            "'sub_status' not provided or is not valid",
        )

    def test_job_update_sub_status_empty_value(self):
        """Test job update sub status with empty sub-status"""
        self._authorize()

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]), format="json"
        )

        self.assertEqual(response_sub_status.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response_sub_status.data.get("message"),
            "'sub_status' not provided or is not valid",
        )

    def test_job_update_sub_status_wrong_user(self):
        """Test job update sub status with unauthorized user"""
        self._authorize(username="test_user_2")

        job_id = "8317718f-5c0d-4fb6-9947-72e480b85048"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        self.assertEqual(response_sub_status.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            response_sub_status.data.get("message"), f"Job [{job_id}] not found"
        )

    def test_job_update_sub_status_not_running(self):
        """Test job update sub status not in running state"""
        self._authorize()

        job_id = "57fc2e4d-267f-40c6-91a3-38153272e764"
        response_sub_status = self.client.patch(
            reverse("v1:jobs-sub-status", args=[job_id]),
            format="json",
            data={"sub_status": "MAPPING"},
        )

        self.assertEqual(response_sub_status.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_sub_status.data.get("message"),
            "Cannot update 'sub_status' when is not in RUNNING status. (Currently SUCCEEDED)",
        )

    def test_user_has_access_to_job_result_from_provider_function(self):
        """
        User has access to job result from a function provider
        as the authot of the job
        """
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec87"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"somekey":1}')

    def test_provider_admin_has_no_access_to_job_result_from_provider_function(self):
        """
        A provider admin has no access to job result from a function provider
        if it's not the author of the job
        """
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_3")
            self.client.force_authenticate(user=user)

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec87"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), None)

    def test_stop_job(self):
        """Tests job stop."""
        self._authorize()

        job_stop_response = self.client.post(
            reverse(
                "v1:jobs-stop",
                args=["8317718f-5c0d-4fb6-9947-72e480b8a348"],
            ),
            format="json",
        )
        self.assertEqual(job_stop_response.status_code, status.HTTP_200_OK)
        job = Job.objects.filter(
            id__exact="8317718f-5c0d-4fb6-9947-72e480b8a348"
        ).first()
        self.assertEqual(job.status, Job.STOPPED)
        self.assertTrue(
            "Job has been stopped." in job_stop_response.data.get("message")
        )

    def test_job_logs_by_author_for_function_without_provider(self):
        """Tests job log by job author."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("logs"), "log entry 2")

    def test_job_logs_by_author_for_function_with_provider(self):
        """Tests job log by job author."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_job_logs_by_function_provider(self):
        """Tests job log by fuction provider."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)

            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("logs"), "log entry 1")

    def test_job_provider_logs(self):
        """Tests job log by fuction provider."""
        shutil.copytree(self._fake_media_path, self.MEDIA_ROOT, dirs_exist_ok=True)
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)

            jobs_response = self.client.get(
                reverse(
                    "v1:jobs-provider-logs",
                    args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"],
                ),
                format="json",
            )

            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("logs"), "provider log entry 1")

    def test_job_provider_logs_forbidden(self):
        """Tests job log by fuction provider."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)

            jobs_response = self.client.get(
                reverse(
                    "v1:jobs-provider-logs",
                    args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"],
                ),
                format="json",
            )

            self.assertEqual(jobs_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_job_provider_logs_not_fount_empty(self):
        """Tests job log by fuction provider."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_3")
            self.client.force_authenticate(user=user)

            job_id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec87"
            jobs_response = self.client.get(
                reverse(
                    "v1:jobs-provider-logs",
                    args=[job_id],
                ),
                format="json",
            )

            self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(
                jobs_response.data.get("message"),
                f"Logs for job[{job_id}] are not found",
            )

    def test_job_logs(self):
        """Tests job log non-authorized."""
        with self.settings(MEDIA_ROOT=self.MEDIA_ROOT):
            user = models.User.objects.get(username="test_user_3")
            self.client.force_authenticate(user=user)

            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_runtime_jobs_post(self):
        """Tests runtime jobs POST endpoint."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

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

        expected_message = (
            f"RuntimeJob object [runtime_job_new] "
            f"created for serverless job id [{job_id}]."
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get("message"), expected_message)

        runtime_job = RuntimeJob.objects.get(runtime_job="runtime_job_new")

        self.assertEqual(
            str(runtime_job.job.id), "8317718f-5c0d-4fb6-9947-72e480b8a348"
        )
        self.assertEqual(runtime_job.runtime_session, "session_id_new")

    def test_runtime_jobs_get(self):
        """Tests list runtime jobs GET endpoint."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        # Job with multiple runtime jobs
        response = self.client.get(
            reverse(
                "v1:jobs-runtime-jobs", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        runtime_jobs = response.data["runtime_jobs"]
        self.assertEqual(len(runtime_jobs), 2)
        expected = [
            {"runtime_job": "runtime_job_1", "runtime_session": "session_id_1"},
            {"runtime_job": "runtime_job_2", "runtime_session": "session_id_2"},
        ]
        for job in runtime_jobs:
            self.assertIn(job, expected)

        # Job with a single runtime job
        response = self.client.get(
            reverse(
                "v1:jobs-runtime-jobs", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        runtime_jobs = response.data["runtime_jobs"]
        self.assertEqual(len(runtime_jobs), 1)
        runtime_job = runtime_jobs[0]
        self.assertEqual(runtime_job.get("runtime_job"), "runtime_job_3")
        self.assertEqual(runtime_job.get("runtime_session"), "session_id_3")

        # Job with no runtime jobs
        response = self.client.get(
            reverse(
                "v1:jobs-runtime-jobs",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec86"],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        runtime_jobs = response.data["runtime_jobs"]
        self.assertEqual(runtime_jobs, [])

    def test_job_list_internal_server_error(self):
        """Tests that unexpected exceptions return 500 with proper message."""
        self._authorize()

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

            self.assertEqual(
                response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            self.assertEqual(response.data.get("message"), "Internal server error")

    def test_job_list_error(self):
        """Tests that unexpected exceptions return 500 with proper message."""
        self._authorize()

        with patch(
            "api.use_cases.jobs.list.JobsListUseCase.execute",
            side_effect=Exception("Database connection failed"),
        ):
            response = self.client.get(reverse("v1:jobs-list"), format="json")

            self.assertEqual(
                response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            self.assertEqual(response.data.get("message"), "Internal server error")
