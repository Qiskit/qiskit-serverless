"""Tests program APIs."""

import os

from django.urls import reverse
from django.contrib.auth import models
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch


class TestAvailableDependenciesVersion(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()  # never remove this line, or the fixtures won't be loaded
        cls.env_patcher = patch.dict(
            os.environ,
            {
                "GATEWAY_DYNAMIC_DEPENDENCIES": "requirements-test-dynamic-dependencies.txt"
            },
            clear=False,
        )
        cls.env_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls.env_patcher.stop()
        super().tearDownClass()

    def test_available_dependencies_version(self):
        """Tests available dependencies version."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse("v1:dependencies-versions")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), ["pendulum>=3.0.0", "wheel>=0.45.1"])
