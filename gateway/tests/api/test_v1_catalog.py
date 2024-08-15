"""Tests catalog APIs."""

from django.contrib.auth import models
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from api.models import Program


class TestCatalogApi(APITestCase):
    """TestCatalogApi."""

    fixtures = ["tests/fixtures/catalog_fixtures.json"]

    def test_catalog_list_non_auth_user(self):
        """Tests catalog list non-authenticated."""
        url = reverse("v1:catalog-list")
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        public_function = response.data[0]
        self.assertEqual(public_function.get("available"), False)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)

    def test_catalog_list_with_auth_user_without_run_permission(self):
        """Tests catalog list authenticated without run permission."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse("v1:catalog-list")
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        public_function = response.data[0]
        self.assertEqual(public_function.get("available"), False)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)

    def test_catalog_list_with_auth_user_with_run_permission(self):
        """Tests catalog list authenticated with run permission."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        url = reverse("v1:catalog-list")
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        public_function = response.data[0]
        self.assertEqual(public_function.get("available"), True)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)

    def test_catalog_retrieve_non_auth_user(self):
        """Tests catalog retrieve non-authenticated."""
        url = reverse(
            "v1:catalog-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]
        )
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_function = response.data
        self.assertEqual(public_function.get("available"), False)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)
        self.assertTrue(isinstance(public_function.get("additional_info"), dict))

    def test_catalog_404_retrieve_non_auth_user(self):
        """Tests catalog retrieve a non-existent function as non-authenticated."""
        url = reverse(
            "v1:catalog-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec83"]
        )
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_catalog_404_retrieve_auth_user(self):
        """Tests catalog retrieve a non-existent function as authenticated."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        
        url = reverse(
            "v1:catalog-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec83"]
        )
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_catalog_retrieve_with_auth_user_without_run_permission(self):
        """Tests catalog retrieve as authenticated without run permission."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        url = reverse(
            "v1:catalog-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]
        )
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_function = response.data
        self.assertEqual(public_function.get("available"), False)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)
        self.assertTrue(isinstance(public_function.get("additional_info"), dict))

    def test_catalog_retrieve_with_auth_user_with_run_permission(self):
        """Tests catalog retrieve as authenticated with run permission."""
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)

        url = reverse(
            "v1:catalog-detail", args=["1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"]
        )
        response = self.client.get(url, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_function = response.data
        self.assertEqual(public_function.get("available"), True)
        self.assertEqual(public_function.get("title"), "Public-Function")
        self.assertEqual(public_function.get("type"), Program.APPLICATION)
        self.assertTrue(isinstance(public_function.get("additional_info"), dict))
