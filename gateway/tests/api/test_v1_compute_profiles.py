"""Tests the compute-profiles discovery API."""

from django.urls import reverse
from django.contrib.auth import models
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import ComputeProfile


class TestComputeProfiles(APITestCase):
    """Tests for GET /api/v1/compute-profiles/."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def setUp(self):
        super().setUp()
        # A CPU-only profile and a GPU one, created out of id order to prove the view sorts.
        ComputeProfile.objects.create(compute_profile_id="24x120x1l40s", name="m", cpu="24", memory="120", gpu="1l40s")
        ComputeProfile.objects.create(compute_profile_id="24x120", name="s", cpu="24", memory="120")

    def test_lists_registered_profiles(self):
        """Returns every registered profile, ordered by id, with the exposed fields (no name)."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse("v1:compute-profiles")
        response = self.client.get(url, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {"compute_profile_id": "24x120", "cpu": "24", "gpu": None, "memory": "120"},
            {"compute_profile_id": "24x120x1l40s", "cpu": "24", "gpu": "1l40s", "memory": "120"},
        ]

    def test_name_is_not_exposed(self):
        """The compute-profile name must never surface, even though rows carry one."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("v1:compute-profiles"), format="json")

        assert all("name" not in row for row in response.json())

    def test_cpu_only_profile_has_null_gpu(self):
        """A CPU-only profile reports gpu=None, which is what lets a client filter the GPU tiers."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("v1:compute-profiles"), format="json")

        by_id = {row["compute_profile_id"]: row for row in response.json()}
        assert by_id["24x120"]["gpu"] is None
        assert by_id["24x120x1l40s"]["gpu"] == "1l40s"

    def test_requires_authentication(self):
        """Unauthenticated requests are rejected."""
        response = self.client.get(reverse("v1:compute-profiles"), format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
