"""Tests program APIs."""

from django.urls import reverse
from django.contrib.auth import models
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase


class TestAvailableDependenciesVersion(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    @override_settings(
        GATEWAY_DYNAMIC_DEPENDENCIES="requirements-test-dynamic-dependencies.txt"
    )
    def test_available_dependencies_version(self):
        """Tests available dependencies version."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse("v1:dependencies-versions")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), ["pendulum>=3.0.0", "wheel>=0.45.1"])
