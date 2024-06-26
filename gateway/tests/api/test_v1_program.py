"""Tests program APIs."""

import json
import os

from django.contrib.auth import models
from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Job, Program


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
        self.assertEqual(len(programs_response.data), 1)
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Program",
        )

    def test_provider_programs_list(self):
        """Tests programs list authorized."""

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 1)
        self.assertEqual(
            programs_response.data[0].get("provider"),
            "default",
        )
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Docker Image Program",
        )

    def test_program_list_with_title_query_parameter(self):
        """Tests program list filtered with title."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        programs_response = self.client.get(
            reverse("v1:programs-list"), {"title": "Program"}, format="json"
        )

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 1)
        self.assertEqual(
            programs_response.data[0].get("title"),
            "Program",
        )

        empty_programs_response = self.client.get(
            reverse("v1:programs-list"), {"title": "Non existing name"}, format="json"
        )
        self.assertEqual(empty_programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(empty_programs_response.data), 0)

    def test_run(self):
        """Tests run existing authorized."""

        user = models.User.objects.get(username="test_user_3")
        self.client.force_authenticate(user=user)

        arguments = json.dumps({"MY_ARGUMENT_KEY": "MY_ARGUMENT_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/run/",
            data={
                "title": "Program",
                "entrypoint": "program.py",
                "arguments": arguments,
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
        self.assertEqual(job.status, Job.QUEUED)
        self.assertEqual(job.arguments, arguments)
        self.assertEqual(job.program.dependencies, "[]")
        self.assertEqual(job.config.min_workers, 1)
        self.assertEqual(job.config.max_workers, 5)
        self.assertEqual(job.config.workers, None)
        self.assertEqual(job.config.auto_scaling, True)

    def test_upload_private_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
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
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("provider"), None)

    def test_upload_custom_image_without_provider(self):
        """Tests upload end-point authorized."""

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

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
        self.assertEqual(programs_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_custom_image_without_access_to_the_provider(self):
        """Tests upload end-point authorized."""

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "icr.io/awesome-namespace/awesome-title",
                "provider": "default",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "default/Private function",
                "dependencies": "[]",
                "env_vars": env_vars,
                "image": "icr.io/awesome-namespace/awesome-title",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_provider_function(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

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
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("provider"), "default")

    def test_upload_provider_function_with_title(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
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
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("provider"), "default")
        self.assertEqual(
            programs_response.data.get("entrypoint"), "test_user_3_program.py"
        )
        self.assertEqual(programs_response.data.get("title"), "Provider Function")
        self.assertRaises(
            Program.DoesNotExist,
            Program.objects.get,
            title="default/Provider Function",
        )

    def test_upload_authorization_error(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

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
        self.assertEqual(programs_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_upload_provider_function_with_description(self):
        """Tests upload end-point authorized."""

        fake_file = ContentFile(b"print('Hello World')")
        fake_file.name = "test_run.tar"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        env_vars = json.dumps({"MY_ENV_VAR_KEY": "MY_ENV_VAR_VALUE"})
        description = "sample function implemented in a custom image"
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
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("provider"), "default")

        programs_response = self.client.get(reverse("v1:programs-list"), format="json")

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(programs_response.data), 2)
        found = False
        for resp_data in programs_response.data:
            if resp_data.get("title") == "Provider Function":
                self.assertEqual(
                    resp_data.get("description"),
                    description,
                )
                found = True
        self.assertTrue(found)

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
