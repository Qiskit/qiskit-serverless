"""Tests quantum function APIs."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestNestedProgramApi(APITestCase):
    """TestNestedProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_programs_non_auth_user(self):
        """Tests quantum function list non-authorized."""
        url = reverse("v1:nested-programs-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_programs_list(self):
        """Tests quantum functions list authorized."""

        auth = reverse("rest_login")
        resp = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = resp.data.get("access_token")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.get(
            reverse("v1:nested-programs-list"), format="json"
        )

        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("count"), 1)
        self.assertEqual(
            programs_response.data.get("results")[0].get("title"), "quantum_function"
        )

    def test_program_detail(self):
        """Tests quantum_function detail authorized."""
        auth = reverse("rest_login")
        resp = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = resp.data.get("access_token")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        programs_response = self.client.get(
            reverse(
                "v1:nested-programs-detail",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"],
            ),
            format="json",
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)
        self.assertEqual(programs_response.data.get("title"), "quantum_function")
        self.assertEqual(programs_response.data.get("entrypoint"), "quantum_function.py")
