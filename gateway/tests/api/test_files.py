"""Tests files api."""
import os

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class TestFilesApi(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_files_list_non_authorized(self):
        """Tests files list non-authorized."""
        url = reverse("v1:files-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_files_list(self):
        """Tests files list."""

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )

        with self.settings(MEDIA_ROOT=media_root):
            auth = reverse("rest_login")
            response = self.client.post(
                auth, {"username": "test_user", "password": "123"}, format="json"
            )
            token = response.data.get("access")
            self.client.credentials(HTTP_AUTHORIZATION="Bearer " + token)
            url = reverse("v1:files-list")
            response = self.client.get(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, ["artifact.tar"])
