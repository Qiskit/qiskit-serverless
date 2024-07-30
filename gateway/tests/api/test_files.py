"""Tests files api."""

import os
from urllib.parse import quote_plus

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import models


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
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-list")
            response = self.client.get(url, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {"results": ["artifact.tar"]})

    def test_provider_files_list(self):
        """Tests files list."""

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-list")
            response = self.client.get(url, data={"provider": "default"}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {"results": ["provider_artifact.tar"]})

    def test_non_existing_file_download(self):
        """Tests downloading non-existing file."""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-download")
        response = self.client.get(
            url, data={"file": "non_existing.tar"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_file_download(self):
        """Tests downloading non-existing file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url, data={"file": "artifact.tar"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.streaming)

    def test_provider_file_download(self):
        """Tests downloading non-existing file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url,
                data={"file": "provider_artifact.tar", "provider": "default"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.streaming)

    def test_file_delete(self):
        """Tests delete file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with open(
            os.path.join(media_root, "test_user", "artifact_delete.tar"), "w"
        ) as fp:
            fp.write("This is first line")
            print(fp)
            fp.close()

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-delete")
            response = self.client.delete(
                url, data={"file": "artifact_delete.tar"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_provider_file_delete(self):
        """Tests delete file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with open(
            os.path.join(media_root, "default", "artifact_delete.tar"), "w"
        ) as fp:
            fp.write("This is first line")
            print(fp)
            fp.close()

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-delete")
            response = self.client.delete(
                url,
                data={"file": "artifact_delete.tar", "provider": "default"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_existing_file_delete(self):
        """Tests delete file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-delete")
            response = self.client.delete(
                url, data={"file": "artifact_delete.tar"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_file_upload(self):
        """Tests uploading existing file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-upload")
            with open("README.md") as f:
                response = self.client.post(
                    url,
                    data={"file": f},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(os.path.join(media_root, "test_user", "README.md"))
                os.remove(os.path.join(media_root, "test_user", "README.md"))

    def test_provider_file_upload(self):
        """Tests uploading existing file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-upload")
            with open("README.md") as f:
                response = self.client.post(
                    url,
                    data={"file": f, "provider": "default"},
                    format="multipart",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(os.path.join(media_root, "test_user", "README.md"))
                os.remove(os.path.join(media_root, "default", "README.md"))

    def test_escape_directory(self):
        """Tests directory escape / injection."""
        with self.settings(
            MEDIA_ROOT=os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "resources",
                "fake_media",
            )
        ):
            user = models.User.objects.get(username="test_user")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url, data={"file": "../test_user_2/artifact_2.tar"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

            response = self.client.get(
                url, data={"file": "../test_user_2/artifact_2.tar/"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
