"""Tests program APIs."""
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from api.models import Job, JobConfig
import json


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

    def test_public(self):
        """Tests public flag."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.get(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/",
            format="json",
        )
        public = programs_response.json()["public"]
        self.assertEqual(public, False)

        programs_response = self.client.patch(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/",
            data={
                "public": True,
            },
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        programs_response = self.client.get(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/",
            format="json",
        )
        public = programs_response.json()["public"]
        self.assertEqual(public, True)

    def test_runtime_job(self):
        """Tests run existing authorized."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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

        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user_2", "password": "123"}, format="json"
        )
        token_2 = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token_2)

        programs_response = self.client.get(
            "/api/v1/runtime_jobs/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

    def test_add_runtimejob(self):
        """Tests run existing authorized."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

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

    def test_catalog_entry(self):
        """Tests catalog entry."""

        # Non-owner
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user_2", "password": "123"}, format="json"
        )
        token_2 = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token_2)

        # list catalog
        programs_response = self.client.get(
            "/api/v1/catalog_entries/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

        id = programs_response.json()["results"][0]["id"]
        programs_response = self.client.get(
            "/api/v1/catalog_entries/" + str(id) + "/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        # Update catalog
        programs_response = self.client.patch(
            "/api/v1/catalog_entries/" + str(id) + "/",
            data={"tags": "newtag"},
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_403_FORBIDDEN)

        # Program owner
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        # list catalog
        programs_response = self.client.get(
            "/api/v1/catalog_entries/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 2)

        id = programs_response.json()["results"][0]["id"]
        programs_response = self.client.get(
            "/api/v1/catalog_entries/" + str(id) + "/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        # Update catalog
        programs_response = self.client.patch(
            "/api/v1/catalog_entries/" + str(id) + "/",
            data={"tags": "newtag"},
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/" + str(id) + "/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json()["tags"], "newtag")

        # delete catalog
        programs_response = self.client.delete(
            "/api/v1/catalog_entries/" + str(id) + "/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_204_NO_CONTENT)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)
        self.assertNotEqual(programs_response.json()["results"][0]["id"], id)

    def test_to_catalog(self):
        """Tests add catalog entry."""

        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        # to catalog entry
        programs_response = self.client.post(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/to_catalog/",
            data={
                "title": "AddedCatalog",
                "description": "description of AddedCatalog",
                "tags": "[tag1, tag2]",
                "status": "PRIVATE",
            },
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_400_BAD_REQUEST)

        programs_response = self.client.patch(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/",
            data={
                "public": True,
            },
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        # to catalog entry
        programs_response = self.client.post(
            "/api/v1/programs/1a7947f9-6ae8-4e3d-ac1e-e7d608deec82/to_catalog/",
            data={
                "title": "AddedCatalog",
                "description": "description of AddedCatalog",
                "tags": "[tag1, tag2]",
                "status": "PRIVATE",
            },
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        # list catalog
        programs_response = self.client.get(
            "/api/v1/catalog_entries/",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 3)

    def test_list_catalog_entry(self):
        """Tests list catalog entry."""

        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/?tags=tag3",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/?tags=tag2",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/?title=Entry1",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/?title=Entry",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 2)

        programs_response = self.client.get(
            "/api/v1/catalog_entries/?description=1",
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.json().get("count"), 1)
