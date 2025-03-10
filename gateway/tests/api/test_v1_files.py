"""Tests files api."""

import os
from urllib.parse import urlencode

from django.urls import reverse
from pytest import mark
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import models


class TestFilesApi(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/files_fixtures.json"]

    def test_files_list_non_authorized(self):
        """Tests files list non-authorized."""
        url = reverse("v1:files-list")
        response = self.client.get(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_files_list_with_empty_params(self):
        """Tests files list using empty params"""

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
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_files_list_from_user_working_dir(self):
        """Tests files list with working dir as user"""

        function = "personal-program"

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
            response = self.client.get(
                url,
                {
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {"results": ["artifact_2.tar"]})

    def test_files_list_from_user_without_access_to_function(self):
        """Tests files list with working dir as user where the user has no access to the function"""

        provider = "default"
        function = "Program"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(
            url,
            {
                "provider": provider,
                "function": function,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_files_list_from_user_with_access_to_function(self):
        """Tests files list with working dir as user where the user has access to the function"""

        provider = "default"
        function = "Program"

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
            response = self.client.get(
                url,
                {
                    "provider": provider,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data, {"results": ["user_program_artifact.tar"]})

    def test_files_list_from_a_provider_that_not_exist(self):
        """Tests files list with a provider that it doesn't exist"""

        provider = "noexist"
        function = "Program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(
            url,
            {
                "provider": provider,
                "function": function,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_files_provider_list_using_provider_working_dir(self):
        """Tests files provider list with working dir as provider"""

        provider = "default"
        function = "Program"

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
            url = reverse("v1:files-provider-list")
            response = self.client.get(
                url,
                {
                    "provider": provider,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                response.data, {"results": ["provider_program_artifact.tar"]}
            )

    def test_files_provider_list_with_a_user_that_has_no_access_to_provider(self):
        """Tests files provider list with working dir as provider"""

        provider = "default"
        function = "Program"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-list")
        response = self.client.get(
            url,
            {
                "provider": provider,
                "function": function,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_existing_file_download(self):
        """Tests downloading non-existing file."""

        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            file = "non_existing_file.tar"
            function = "personal-program"

            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url,
                {
                    "file": file,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_file_download(self):
        """Tests downloading an existing file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            file = "artifact_2.tar"
            function = "personal-program"

            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url,
                {
                    "file": file,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.streaming)

    def test_non_existing_provider_file_download(self):
        """Tests downloading a non-existing file from a provider storage."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            file = "non-existing_artifact.tar"
            provider = "default"
            function = "Program"

            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-provider-download")
            response = self.client.get(
                url,
                {
                    "file": file,
                    "provider": provider,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_provider_file_download(self):
        """Tests downloading a file from a provider storage."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))

        with self.settings(MEDIA_ROOT=media_root):
            file = "provider_program_artifact.tar"
            provider = "default"
            function = "Program"

            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-provider-download")
            response = self.client.get(
                url,
                {
                    "file": file,
                    "provider": provider,
                    "function": function,
                },
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
        function = "personal-program"
        file = "artifact_delete.tar"
        username = "test_user_2"
        functionPath = os.path.join(media_root, username)

        if not os.path.exists(functionPath):
            os.makedirs(functionPath)

        with open(
            os.path.join(functionPath, file),
            "w+",
        ) as fp:
            fp.write("This is first line")
            fp.close()

        with self.settings(MEDIA_ROOT=media_root):
            query_params = {"function": function, "file": file}
            user = models.User.objects.get(username=username)
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-delete")
            response = self.client.delete(f"{url}?{urlencode(query_params)}")
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
        provider = "default"
        function = "Program"
        file = "artifact_delete.tar"
        username = "test_user_2"
        functionPath = os.path.join(media_root, provider, function)

        if not os.path.exists(functionPath):
            os.makedirs(functionPath)

        with open(
            os.path.join(functionPath, file),
            "w+",
        ) as fp:
            fp.write("This is first line")
            fp.close()

        with self.settings(MEDIA_ROOT=media_root):
            query_params = {"function": function, "provider": provider, "file": file}
            user = models.User.objects.get(username=username)
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-provider-delete")
            response = self.client.delete(f"{url}?{urlencode(query_params)}")
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
        function = "personal-program"
        file = "non-existing-artifact_delete.tar"
        username = "test_user_2"

        with self.settings(MEDIA_ROOT=media_root):
            query_params = {"function": function, "file": file}
            user = models.User.objects.get(username=username)
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-delete")
            response = self.client.delete(f"{url}?{urlencode(query_params)}")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_existing_provider_file_delete(self):
        """Tests delete file."""
        media_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
        media_root = os.path.normpath(os.path.join(os.getcwd(), media_root))
        provider = "default"
        function = "Program"
        file = "non-existing-artifact_delete.tar"
        username = "test_user_2"

        with self.settings(MEDIA_ROOT=media_root):
            query_params = {"function": function, "provider": provider, "file": file}
            user = models.User.objects.get(username=username)
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-provider-delete")
            response = self.client.delete(f"{url}?{urlencode(query_params)}")
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
            function = "personal-program"
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-upload")

            with open("README.md") as f:
                query_params = {"function": function}
                response = self.client.post(
                    f"{url}?{urlencode(query_params)}",
                    {"file": f},
                    format="multipart",
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(os.path.join(media_root, "test_user_2", "README.md"))
                os.remove(os.path.join(media_root, "test_user_2", "README.md"))

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
            provider = "default"
            function = "Program"
            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-provider-upload")

            with open("README.md") as f:
                query_params = {"function": function, "provider": provider}
                response = self.client.post(
                    f"{url}?{urlencode(query_params)}",
                    {"file": f},
                    format="multipart",
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertTrue(
                    os.path.join(media_root, "default", "Program", "README.md")
                )
                os.remove(os.path.join(media_root, "default", "Program", "README.md"))

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
            file = "../test_user/artifact.tar"
            function = "personal-program"

            user = models.User.objects.get(username="test_user_2")
            self.client.force_authenticate(user=user)
            url = reverse("v1:files-download")
            response = self.client.get(
                url,
                {
                    "file": file,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

            file = "../test_user/artifact.tar/"
            response = self.client.get(
                url,
                {
                    "file": file,
                    "function": function,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
