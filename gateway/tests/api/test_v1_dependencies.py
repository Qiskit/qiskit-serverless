"""Tests program APIs."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestAvailableDependenciesVersion(APITestCase):
    """TestProgramApi."""

    def test_available_dependencies_version(self):
        """Tests available dependencies version."""
        url = reverse("v1:available-dependencies-versions")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), ["pendulum>=3.0.0", "wheel>=0.45.1"])
