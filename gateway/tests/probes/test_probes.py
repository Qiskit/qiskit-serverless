"""Tests probess."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestProbes(APITestCase):
    """TestProbles."""

    def test_liveness(self):
        """Tests liveness."""
        jobs_response = self.client.get(reverse("liveness"))
        self.assertEqual(jobs_response.status_code, status.HTTP_200_OK)

    def test_readiness(self):
        """Tests readiness."""
        jobs_response = self.client.get(reverse("readiness"))
        self.assertEqual(jobs_response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
