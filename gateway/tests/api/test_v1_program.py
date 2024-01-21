"""Tests program APIs."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from api.models import Job, JobConfig


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

        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("count"), 1)
        self.assertEqual(
            programs_response.data.get("results")[0].get("title"),
            "Program",
        )

    def test_program_detail(self):
        """Tests program detail authorized."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.post(
            "/api/v1/programs/run_existing/",
            data={
                "title": "Program",
                "entrypoint": "program.py",
                "arguments": {},
                "dependencies": [],
                "config": '{"workers": null, "min_workers": 1, "max_workers": 5, "auto_scaling": true}',
            },
            format="json",
        )
        job_id = programs_response.data.get("id")
        job = Job.objects.get(id=job_id)
        self.assertEqual(job.config.min_workers, 1)
        self.assertEqual(job.config.max_workers, 5)
        self.assertEqual(job.config.workers, None)
        self.assertEqual(job.config.auto_scaling, True)

    def test_set_public(self):
        """Tests run existing authorized."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        response = self.client.post(
            "/api/v1/programs/set_public/",
            data={
                "title": "Program",
                "public": True,
            },
            format="json",
        )
        self.assertEqual(response.json()["public"], True)
        self.assertEqual(response.json()["title"], "Program")
