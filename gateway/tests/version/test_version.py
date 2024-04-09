"""Test version."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestProbes(APITestCase):
    """TestVersion."""

    def test_version(self):
        """Tests version."""
        jobs_response = self.client.get(reverse("version"))
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)
