"""Tests jobs APIs."""

import os
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Job
from django.contrib.auth import models


class TestJobApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def _authorize(self):
        """Authorize client."""
        user = models.User.objects.get(username="test_user")
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
        self.assertEqual(jobs_response.data.get("count"), 3)
        self.assertEqual(
            jobs_response.data.get("results")[0].get("status"), "SUCCEEDED"
        )
        self.assertEqual(
            jobs_response.data.get("results")[0].get("result"), '{"somekey":1}'
        )

    def test_job_detail(self):
        """Tests job detail authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("status"), "SUCCEEDED")
        self.assertEqual(jobs_response.data.get("result"), '{"somekey":1}')

    def test_not_authorized_job_detail(self):
        """Tests job detail fails trying to access to other user job."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec84"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_job_save_result(self):
        """Tests job results save."""
        self._authorize()

        jobs_response = self.client.post(
            reverse("v1:jobs-result", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]),
            format="json",
            data={"result": {"ultimate": 42}},
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("status"), "SUCCEEDED")
        self.assertEqual(jobs_response.data.get("result"), '{"ultimate": 42}')

    def test_stop_job(self):
        """Tests job stop."""
        self._authorize()

        job_stop_response = self.client.post(
            reverse(
                "v1:jobs-stop",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec83"],
            ),
            format="json",
        )
        self.assertEqual(job_stop_response.status_code, status.HTTP_200_OK)
        job = Job.objects.filter(
            id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec83"
        ).first()
        self.assertEqual(job.status, Job.STOPPED)
        self.assertEqual(job_stop_response.data.get("message"), "Job has been stopped.")

    def test_job_logs_by_author_for_function_without_provider(self):
        """Tests job log by job author."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]),
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
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No available logs")

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
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No available logs")

    def test_job_logs_type_user_by_author(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        with self.settings(MEDIA_ROOT=media_root):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]),
                {"log_type": "user"},
                format="json",
            )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertTrue("test_user user log line 1" in jobs_response.data.get("logs"))

    def test_job_logs_type_user_by_provider(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        with self.settings(MEDIA_ROOT=media_root):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                {"log_type": "user"},
                format="json",
            )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertTrue("test_user_2 user log line 1" in jobs_response.data.get("logs"))

    def test_job_logs_type_user(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user_3")
        self.client.force_authenticate(user=user)

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        with self.settings(MEDIA_ROOT=media_root):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                {"log_type": "user"},
                format="json",
            )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No available logs")

    def test_job_logs_type_function_with_provider_by_user(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        with self.settings(MEDIA_ROOT=media_root):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                {"log_type": "function"},
                format="json",
            )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("logs"), "No available logs")

    def test_job_logs_type_function_by_provider(self):
        """Tests job log non-authorized."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        with self.settings(MEDIA_ROOT=media_root):
            jobs_response = self.client.get(
                reverse("v1:jobs-logs", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec85"]),
                {"log_type": "function"},
                format="json",
            )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertTrue("Function log line 1" in jobs_response.data.get("logs"))
