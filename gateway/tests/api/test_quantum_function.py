"""Tests quantum function APIs."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestQuantumFunctionApi(APITestCase):
    """TestQuantumFunctionApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_quantum_functions_non_auth_user(self):
        """Tests quantum function list non-authorized."""
        url = reverse("v1:quantum-functions-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_quantum_functions_list(self):
        """Tests quantum functions list authorized."""

        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access_token")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        quantum_functions_response = self.client.get(
            reverse("v1:quantum-functions-list"), format="json"
        )

        self.assertEqual(quantum_functions_response.status_code, status.HTTP_200_OK)
        self.assertEqual(quantum_functions_response.data.get("count"), 1)
        self.assertEqual(
            quantum_functions_response.data.get("results")[0].get("title"),
            "quantum_function",
        )

    def test_quantum_function_detail(self):
        """Tests quantum_function detail authorized."""
        auth = reverse("rest_login")
        response = self.client.post(
            auth, {"username": "test_user", "password": "123"}, format="json"
        )
        token = response.data.get("access_token")
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)

        quantum_functions_response = self.client.get(
            reverse(
                "v1:quantum-functions-detail",
                args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"],
            ),
            format="json",
        )
        self.assertEqual(quantum_functions_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            quantum_functions_response.data.get("title"), "quantum_function"
        )
        self.assertEqual(
            quantum_functions_response.data.get("entrypoint"), "quantum_function.py"
        )
