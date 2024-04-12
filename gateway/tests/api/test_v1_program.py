"""Tests program APIs."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from api.models import Job, JobConfig
import json
from django.contrib.auth import models


class TestProgramApi(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_programs_non_auth_user(self):
        """Tests program list non-authorized."""
        url = reverse("v1:programs-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_programs_list(self):
        """Tests programs list authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("count"), 1)
        self.assertEqual(
            programs_response.data.get("results")[0].get("title"),
            "Program",
        )

    def test_program_detail(self):
        """Tests program detail authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        programs_response = self.client.get(
            reverse(
                "v1:programs-detail",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"],
            ),
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("title"), "Program")
        self.assertEqual(programs_response.data.get("entrypoint"), "program.py")

    def test_run_existing(self):
        """Tests run existing authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        programs_response = self.client.post(
            "/api/v1/programs/run_existing/",
            data={
                "title": "Program",
                "entrypoint": "program.py",
                "arguments": "{}",
                "dependencies": "[]",
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
        self.assertEqual(job.config.min_workers, 1)
        self.assertEqual(job.config.max_workers, 5)
        self.assertEqual(job.config.workers, None)
        self.assertEqual(job.config.auto_scaling, True)

    def test_runtime_job(self):
        """Tests run existing authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        programs_response = self.client.get(
            "/api/v1/runtime_jobs/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 3)

        programs_response = self.client.delete(
            "/api/v1/runtime_jobs/runtime_job_1/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_204_NO_CONTENT)

        programs_response = self.client.get(
            "/api/v1/runtime_jobs/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 2)

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        programs_response = self.client.get(
            "/api/v1/runtime_jobs/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

    def test_add_runtimejob(self):
        """Tests run existing authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        programs_response = self.client.post(
            "/api/v1/jobs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec83/add_runtimejob/",
            data={
                "runtime_job": "runtime_job_4",
            },
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        programs_response = self.client.get(
            "/api/v1/runtime_jobs/runtime_job_4/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            programs_response.json()["job"]["id"],
            "1a7947f9-6ae8-4e3d-ac1e-e7d608deec83",
        )

    def test_list_runtimejob(self):
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        programs_response = self.client.get(
            "/api/v1/jobs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec83/list_runtimejob/",
            format="json",
        )
        self.assertEqual(programs_response.json(), '["runtime_job_1", "runtime_job_2"]')

        programs_response = self.client.get(
            "/api/v1/jobs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/list_runtimejob/",
            format="json",
        )
        self.assertEqual(programs_response.json(), '["runtime_job_3"]')
