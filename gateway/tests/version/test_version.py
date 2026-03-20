"""Test version."""

import pytest
from django.urls import reverse
from rest_framework import status


class TestProbes:
    """TestVersion."""

    @pytest.fixture(autouse=True)
    def _setup(self, db):
        pass

    def test_version(self, client):
        """Tests version."""
        jobs_response = client.get(reverse("version"))
        assert jobs_response.status_code == status.HTTP_200_OK
