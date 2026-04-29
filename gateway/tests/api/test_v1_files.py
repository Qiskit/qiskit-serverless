"""Tests files api."""

import os
from urllib.parse import urlencode

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import models
from django.core.cache import cache

from core.config_key import ConfigKey
from core.models import Config
from core.services.storage.enums.working_dir import WorkingDir


class TestFilesApi:
    """TestProgramApi."""

    @pytest.fixture(autouse=True)
    def _setup(self, db):
        call_command("loaddata", "tests/fixtures/files_fixtures.json")
        cache.clear()
        Config.add_defaults()
        self.client = APIClient()

    def test_files_list_non_authorized(self):
        """Tests files list non-authorized."""
        url = reverse("v1:files-list")
        response = self.client.get(url, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_files_list_with_empty_params(self):
        """Tests files list using empty params"""
        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(url, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_files_list_from_user_working_dir(self, mock_cos):
        """Tests files list with working dir as user"""
        function = "personal-program"

        mock_cos.put_object_bytes("test_user_2/artifact_2.tar", b"content", WorkingDir.USER_STORAGE)

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
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["artifact_2.tar"]}

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
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_files_list_from_user_with_access_to_function(self, mock_cos):
        """Tests files list with working dir as user where the user has access to the function"""
        provider = "default"
        function = "Program"

        mock_cos.put_object_bytes(
            "test_user_2/default/Program/user_program_artifact.tar", b"content", WorkingDir.USER_STORAGE
        )

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
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["user_program_artifact.tar"]}

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
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_files_provider_list_using_provider_working_dir(self, mock_cos):
        """Tests files provider list with working dir as provider"""
        provider = "default"
        function = "Program"

        mock_cos.put_object_bytes(
            "default/Program/provider_program_artifact.tar", b"content", WorkingDir.PROVIDER_STORAGE
        )

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
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["provider_program_artifact.tar"]}

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
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_non_existing_file_download(self):
        """Tests downloading non-existing file."""
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
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_file_download(self, mock_cos):
        """Tests downloading an existing file."""
        mock_cos.put_object_bytes("test_user_2/artifact_2.tar", b"file content", WorkingDir.USER_STORAGE)

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
        assert response.status_code == status.HTTP_200_OK
        assert response.streaming

    def test_non_existing_provider_file_download(self):
        """Tests downloading a non-existing file from a provider storage."""
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
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_provider_file_download(self, mock_cos):
        """Tests downloading a file from a provider storage."""
        mock_cos.put_object_bytes(
            "default/Program/provider_program_artifact.tar", b"provider content", WorkingDir.PROVIDER_STORAGE
        )

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
        assert response.status_code == status.HTTP_200_OK
        assert response.streaming

    def test_file_delete(self, mock_cos):
        """Tests delete file."""
        function = "personal-program"
        file = "artifact_delete.tar"
        username = "test_user_2"

        mock_cos.put_object_bytes("test_user_2/artifact_delete.tar", b"content to delete", WorkingDir.USER_STORAGE)

        query_params = {"function": function, "file": file}
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-delete")
        response = self.client.delete(f"{url}?{urlencode(query_params)}")
        assert response.status_code == status.HTTP_200_OK

    def test_provider_file_delete(self, mock_cos):
        """Tests delete file."""
        provider = "default"
        function = "Program"
        file = "artifact_delete.tar"
        username = "test_user_2"

        mock_cos.put_object_bytes(
            "default/Program/artifact_delete.tar", b"content to delete", WorkingDir.PROVIDER_STORAGE
        )

        query_params = {"function": function, "provider": provider, "file": file}
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-delete")
        response = self.client.delete(f"{url}?{urlencode(query_params)}")
        assert response.status_code == status.HTTP_200_OK

    def test_non_existing_file_delete(self):
        """Tests delete file."""
        function = "personal-program"
        file = "non-existing-artifact_delete.tar"
        username = "test_user_2"

        query_params = {"function": function, "file": file}
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-delete")
        response = self.client.delete(f"{url}?{urlencode(query_params)}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_non_existing_provider_file_delete(self):
        """Tests delete file."""
        provider = "default"
        function = "Program"
        file = "non-existing-artifact_delete.tar"
        username = "test_user_2"

        query_params = {"function": function, "provider": provider, "file": file}
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-delete")
        response = self.client.delete(f"{url}?{urlencode(query_params)}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_file_upload(self, settings, mock_cos):
        """Tests uploading existing file."""
        settings.UPLOAD_FILE_VALID_MIME_TYPES = ["text/plain"]
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

            assert response.status_code == status.HTTP_200_OK
            assert mock_cos.get_object_bytes("test_user_2/README.md", WorkingDir.USER_STORAGE) is not None

    def test_provider_file_upload(self, settings, mock_cos):
        """Tests uploading existing file."""
        settings.UPLOAD_FILE_VALID_MIME_TYPES = ["text/plain"]
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

            assert response.status_code == status.HTTP_200_OK
            assert mock_cos.get_object_bytes("default/Program/README.md", WorkingDir.PROVIDER_STORAGE) is not None

    def test_provider_file_upload_default_values(self, mock_cos):
        """Tests uploading existing file."""
        provider = "default"
        function = "Program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-upload")

        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )

        with open(path_to_resource_artifact, "rb") as f:
            query_params = {"function": function, "provider": provider}
            response = self.client.post(
                f"{url}?{urlencode(query_params)}",
                {"file": f},
                format="multipart",
            )

            assert response.status_code == status.HTTP_200_OK
            assert mock_cos.get_object_bytes("default/Program/artifact.tar", WorkingDir.PROVIDER_STORAGE) is not None

    def test_file_upload_wrong_type(self, mock_cos):
        """Tests uploading existing file."""
        Config.set(ConfigKey.UPLOAD_FILE_VALID_MIME_TYPES, '["image/jpeg"]')
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

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert mock_cos.get_object_bytes("test_user_2/README.md", WorkingDir.USER_STORAGE) is None

    def test_file_upload_wrong_type_default_values(self, mock_cos):
        """Tests uploading existing file."""
        function = "personal-program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-upload")

        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "test-img.png",
        )

        with open(path_to_resource_artifact, "rb") as f:
            query_params = {"function": function}
            response = self.client.post(
                f"{url}?{urlencode(query_params)}",
                {"file": f},
                format="multipart",
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert mock_cos.get_object_bytes("test_user_2/test-img.png", WorkingDir.USER_STORAGE) is None

    def test_provider_file_upload_no_file(self):
        """Tests uploading existing file."""
        provider = "default"
        function = "Program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-upload")

        query_params = {"function": function, "provider": provider}
        response = self.client.post(
            f"{url}?{urlencode(query_params)}",
            format="multipart",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_file_upload_no_file(self):
        """Tests uploading existing file."""
        function = "personal-program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-upload")

        query_params = {"function": function}
        response = self.client.post(
            f"{url}?{urlencode(query_params)}",
            format="multipart",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_escape_directory(self):
        """Tests directory escape / injection."""
        function = "personal-program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-download")

        response = self.client.get(
            url,
            {
                "file": "../test_user/artifact.tar",
                "function": function,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        response = self.client.get(
            url,
            {
                "file": "../test_user/artifact.tar/",
                "function": function,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
