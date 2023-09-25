"""Tests jobs APIs."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Job


class TestJobApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def _authorize(self):
        """Authorize client."""
        auth = reverse("rest_login")
        resp = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = resp.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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
        self.assertEqual(jobs_response.data.get("count"), 2)
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
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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
