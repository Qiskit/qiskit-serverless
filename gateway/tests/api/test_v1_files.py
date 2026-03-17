"""Tests files api."""

import os
import shutil
from urllib.parse import urlencode

import pytest
from django.contrib.auth import models
from django.core.management import call_command
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.config_key import ConfigKey
from core.models import Config


@pytest.mark.django_db
class TestFilesApi:
    """TestFilesApi."""

    _fake_media_path = os.path.normpath(
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "fake_media",
        )
    )

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):

        call_command("loaddata", "tests/fixtures/files_fixtures.json")
        cache.clear()
        Config.add_defaults()
        settings.MEDIA_ROOT = str(tmp_path)
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

    def test_files_list_from_user_working_dir(self, settings):
        """Tests files list with working dir as user"""
        function = "personal-program"

        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(url, {"function": function}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["artifact_2.tar"]}

    def test_files_list_from_user_without_access_to_function(self):
        """Tests files list with working dir as user where the user has no access to the function"""
        provider = "default"
        function = "Program"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(url, {"provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_files_list_from_user_with_access_to_function(self, settings):
        """Tests files list with working dir as user where the user has access to the function"""
        provider = "default"
        function = "Program"

        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(url, {"provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["user_program_artifact.tar"]}

    def test_files_list_from_a_provider_that_not_exist(self):
        """Tests files list with a provider that it doesn't exist"""
        provider = "noexist"
        function = "Program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-list")
        response = self.client.get(url, {"provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_files_provider_list_using_provider_working_dir(self, settings):
        """Tests files provider list with working dir as provider"""
        provider = "default"
        function = "Program"

        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-list")
        response = self.client.get(url, {"provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"results": ["provider_program_artifact.tar"]}

    def test_files_provider_list_with_a_user_that_has_no_access_to_provider(self):
        """Tests files provider list with working dir as provider"""
        provider = "default"
        function = "Program"

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-list")
        response = self.client.get(url, {"provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_non_existing_file_download(self):
        """Tests downloading non-existing file."""
        file = "non_existing_file.tar"
        function = "personal-program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-download")
        response = self.client.get(url, {"file": file, "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_file_download(self, settings):
        """Tests downloading an existing file."""
        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        file = "artifact_2.tar"
        function = "personal-program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-download")
        response = self.client.get(url, {"file": file, "function": function}, format="json")
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
        response = self.client.get(url, {"file": file, "provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_provider_file_download(self, settings):
        """Tests downloading a file from a provider storage."""
        shutil.copytree(self._fake_media_path, settings.MEDIA_ROOT, dirs_exist_ok=True)

        file = "provider_program_artifact.tar"
        provider = "default"
        function = "Program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-download")
        response = self.client.get(url, {"file": file, "provider": provider, "function": function}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.streaming

    def test_file_delete(self, settings):
        """Tests delete file."""
        function = "personal-program"
        file = "artifact_delete.tar"
        username = "test_user_2"
        function_path = os.path.join(settings.MEDIA_ROOT, username)

        os.makedirs(function_path, exist_ok=True)
        with open(os.path.join(function_path, file), "w+") as fp:
            fp.write("This is first line")

        query_params = {"function": function, "file": file}
        user = models.User.objects.get(username=username)
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-delete")
        response = self.client.delete(f"{url}?{urlencode(query_params)}")
        assert response.status_code == status.HTTP_200_OK

    def test_provider_file_delete(self, settings):
        """Tests delete file."""
        provider = "default"
        function = "Program"
        file = "artifact_delete.tar"
        username = "test_user_2"
        function_path = os.path.join(settings.MEDIA_ROOT, provider, function)

        os.makedirs(function_path, exist_ok=True)
        with open(os.path.join(function_path, file), "w+") as fp:
            fp.write("This is first line")

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

    def test_file_upload(self, settings):
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
        assert os.path.exists(os.path.join(settings.MEDIA_ROOT, "test_user_2", "README.md"))

    def test_provider_file_upload(self, settings):
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
        assert os.path.exists(os.path.join(settings.MEDIA_ROOT, "default", "Program", "README.md"))

    def test_provider_file_upload_default_values(self, settings):
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
        assert os.path.exists(os.path.join(settings.MEDIA_ROOT, "default", "Program", "artifact.tar"))

    def test_file_upload_wrong_type(self, settings):
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
        assert not os.path.exists(os.path.join(settings.MEDIA_ROOT, "test_user_2", "README.md"))

    def test_file_upload_wrong_type_default_values(self, settings):
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
        assert not os.path.exists(os.path.join(settings.MEDIA_ROOT, "test_user_2", "test-png.png"))

    def test_provider_file_upload_no_file(self):
        """Tests uploading existing file."""
        provider = "default"
        function = "Program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-provider-upload")

        query_params = {"function": function, "provider": provider}
        response = self.client.post(f"{url}?{urlencode(query_params)}", format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_file_upload_no_file(self):
        """Tests uploading existing file."""
        function = "personal-program"
        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-upload")

        query_params = {"function": function}
        response = self.client.post(f"{url}?{urlencode(query_params)}", format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_escape_directory(self):
        """Tests directory escape / injection."""
        function = "personal-program"

        user = models.User.objects.get(username="test_user_2")
        self.client.force_authenticate(user=user)
        url = reverse("v1:files-download")

        response = self.client.get(url, {"file": "../test_user/artifact.tar", "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        response = self.client.get(url, {"file": "../test_user/artifact.tar/", "function": function}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
