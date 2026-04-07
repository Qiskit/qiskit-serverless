"""Tests program APIs."""

from django.urls import reverse
from django.contrib.auth import models
from rest_framework import status
from rest_framework.test import APITestCase


class TestAvailableDependenciesVersion(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_available_dependencies_version(self):
        """Tests available dependencies version."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse("v1:dependencies-versions")
        response = self.client.get(url, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            "ffsim==0.0.60",
            "mergedeep==1.3.4",
            "mthree==3.0.0",
            "pyscf==2.11.0",
            "qiskit-addon-aqc-tensor[quimb-jax]==0.2.0",
            "qiskit-addon-obp==0.3.0",
            "qiskit-addon-sqd==0.12.0",
            "qiskit-addon-utils==0.2.0",
            "qiskit-aer==0.17.2",
        ]
