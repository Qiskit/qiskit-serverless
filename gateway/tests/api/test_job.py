"""Tests jobs APIs."""

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

    def test_job_catalog_list(self):
        """Tests job list authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"filter": "catalog"}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 1)
        self.assertEqual(jobs_response.data.get("results")[0].get("status"), "QUEUED")
        self.assertEqual(
            jobs_response.data.get("results")[0].get("result"), '{"somekey":1}'
        )

    def test_job_serverless_list(self):
        """Tests job list authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-list"), {"filter": "serverless"}, format="json"
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("count"), 2)
        job_status = jobs_response.data.get("results")[0].get("status")
        if job_status == "SUCCEEDED":
            self.assertEqual(
                jobs_response.data.get("results")[0].get("result"), '{"somekey":1}'
            )
        elif job_status == "QUEUED":
            self.assertEqual(
                jobs_response.data.get("results")[0].get("result"), '{"somekey":2}'
            )

    def test_job_detail(self):
        """Tests job detail authorized."""
        self._authorize()

        jobs_response = self.client.get(
            reverse("v1:jobs-detail", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("status"), "SUCCEEDED")
        self.assertEqual(jobs_response.data.get("result"), '{"somekey":1}')

    def test_job_provider_detail(self):
        """Tests job detail authorized."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        jobs_response = self.client.get(
            reverse("v1:jobs-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec86"]),
            format="json",
        )
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(jobs_response.data.get("status"), "QUEUED")
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
            reverse("v1:jobs-result", args=["57fc2e4d-267f-40c6-91a3-38153272e764"]),
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
