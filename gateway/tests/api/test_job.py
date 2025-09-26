"""Tests jobs APIs."""

import os
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Job
from django.contrib.auth import models
from django.conf import settings


class TestJobApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

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
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            self._authorize()

            jobs_response = self.client.get(
                reverse("v1:retrieve", args=["8317718f-5c0d-4fb6-9947-72e480b8a348"]),
                format="json",
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"ultimate": 42}')

    def test_job_detail_without_result_param(self):
        """Tests job detail authorized."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
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
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
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

    def test_job_save_result(self):
        """Tests job results save."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            self._authorize()
            job_id = "57fc2e4d-267f-40c6-91a3-38153272e764"
            jobs_response = self.client.post(
                reverse("v1:jobs-result", args=[job_id]),
                format="json",
                data={"result": {"ultimate": 42}},
            )
            self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
            self.assertEqual(jobs_response.data.get("result"), '{"ultimate": 42}')
            result_path = os.path.join(
                settings.MEDIA_ROOT, "test_user", "results", f"{job_id}.json"
            )
            self.assertTrue(os.path.exists(result_path))
            os.remove(result_path)

    def test_not_authorized_job_save_result(self):
        """Tests job results save."""
        self._authorize()
        job_id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec84"
        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=[job_id]),
            format="json",
            data={"result": {"ultimate": 42}},
        )

        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            jobs_response.data.get("message"),
            f"Job [{job_id}] not found",
        )

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
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
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
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
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
        self.assertEqual(job_stop_response.data.get("message"), "Job has been stopped.")

    def test_job_logs_by_author_for_function_without_provider(self):
        """Tests job log by job author."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "log entry 2")

    def test_job_logs_by_author_for_function_with_provider(self):
        """Tests job log by job author."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_job_logs_by_function_provider(self):
        """Tests job log by fuction provider."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "log entry 1")

    def test_job_logs(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user_3")
        self.client.force_authenticate(user=user)

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_403_FORBIDDEN)
