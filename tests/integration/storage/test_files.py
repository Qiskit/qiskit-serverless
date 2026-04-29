# pylint: disable=import-error
"""Integration tests for the file storage views against a real MinIO instance.

These tests exercise the complete stack:
  HTTP request → view → use-case → FileStorage → COS (MinIO)

Fixtures used (from files_fixtures.json):
  - test_user_2  : has run_program permission on both programs below
  - personal-program  (no provider, Ray runner) → USER_STORAGE
  - Program / default (provider "default", Ray runner) → USER_STORAGE + PROVIDER_STORAGE
"""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urlencode

import pytest
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.urls import reverse
from rest_framework import status


def _tar_file(name: str, content: bytes = b"hello storage") -> InMemoryUploadedFile:
    return InMemoryUploadedFile(
        file=BytesIO(content),
        field_name="file",
        name=name,
        content_type="application/x-tar",
        size=len(content),
        charset=None,
    )


# ── User storage (personal-program, no provider) ───────────────────────────


class TestUserFiles:
    FUNCTION = "personal-program"

    def test_upload_then_list(self, api_client):
        upload_url = f"{reverse('v1:files-upload')}?{urlencode({'function': self.FUNCTION})}"
        api_client.post(upload_url, {"file": _tar_file("upload_list.tar")}, format="multipart")

        response = api_client.get(reverse("v1:files-list"), {"function": self.FUNCTION})

        assert response.status_code == status.HTTP_200_OK
        assert "upload_list.tar" in response.data["results"]

    def test_upload_then_download_content_matches(self, api_client):
        content = b"unique content for download test"
        upload_url = f"{reverse('v1:files-upload')}?{urlencode({'function': self.FUNCTION})}"
        api_client.post(upload_url, {"file": _tar_file("download_check.tar", content)}, format="multipart")

        response = api_client.get(
            reverse("v1:files-download"),
            {"function": self.FUNCTION, "file": "download_check.tar"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert b"".join(response.streaming_content) == content

    def test_upload_then_delete_then_list_is_empty(self, api_client):
        upload_url = f"{reverse('v1:files-upload')}?{urlencode({'function': self.FUNCTION})}"
        api_client.post(upload_url, {"file": _tar_file("to_delete.tar")}, format="multipart")

        delete_qs = urlencode({"function": self.FUNCTION, "file": "to_delete.tar"})
        api_client.delete(f"{reverse('v1:files-delete')}?{delete_qs}")

        response = api_client.get(reverse("v1:files-list"), {"function": self.FUNCTION})

        assert response.status_code == status.HTTP_200_OK
        assert "to_delete.tar" not in response.data["results"]

    def test_download_nonexistent_returns_404(self, api_client):
        response = api_client.get(
            reverse("v1:files-download"),
            {"function": self.FUNCTION, "file": "ghost.tar"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_returns_404(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "file": "ghost.tar"})
        response = api_client.delete(f"{reverse('v1:files-delete')}?{qs}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_stores_file_in_cos(self, api_client, minio_s3):
        """Verify the file actually lands in the COS bucket, not just via the API."""
        content = b"cos verification content"
        upload_url = f"{reverse('v1:files-upload')}?{urlencode({'function': self.FUNCTION})}"
        api_client.post(upload_url, {"file": _tar_file("cos_check.tar", content)}, format="multipart")

        # The key structure for user storage without provider is: username/filename
        response = minio_s3.get_object(Bucket="ray-test", Key="test_user_2/cos_check.tar")
        assert response["Body"].read() == content


# ── User storage with a provider function (USER_STORAGE, Program/default) ───


class TestUserFilesWithProviderFunction:
    FUNCTION = "Program"
    PROVIDER = "default"

    def test_upload_then_list(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-upload')}?{qs}",
            {"file": _tar_file("user_provider_list.tar")},
            format="multipart",
        )

        response = api_client.get(
            reverse("v1:files-list"),
            {"function": self.FUNCTION, "provider": self.PROVIDER},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "user_provider_list.tar" in response.data["results"]

    def test_upload_then_download_content_matches(self, api_client):
        content = b"provider function user content"
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-upload')}?{qs}",
            {"file": _tar_file("user_provider_dl.tar", content)},
            format="multipart",
        )

        response = api_client.get(
            reverse("v1:files-download"),
            {"function": self.FUNCTION, "provider": self.PROVIDER, "file": "user_provider_dl.tar"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert b"".join(response.streaming_content) == content

    def test_upload_then_delete(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-upload')}?{qs}",
            {"file": _tar_file("user_provider_del.tar")},
            format="multipart",
        )

        del_qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER, "file": "user_provider_del.tar"})
        api_client.delete(f"{reverse('v1:files-delete')}?{del_qs}")

        response = api_client.get(
            reverse("v1:files-list"),
            {"function": self.FUNCTION, "provider": self.PROVIDER},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "user_provider_del.tar" not in response.data["results"]


# ── Provider storage (PROVIDER_STORAGE, Program/default) ────────────────────


class TestProviderFiles:
    FUNCTION = "Program"
    PROVIDER = "default"

    def test_upload_then_list(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-provider-upload')}?{qs}",
            {"file": _tar_file("provider_list.tar")},
            format="multipart",
        )

        response = api_client.get(
            reverse("v1:files-provider-list"),
            {"function": self.FUNCTION, "provider": self.PROVIDER},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "provider_list.tar" in response.data["results"]

    def test_upload_then_download_content_matches(self, api_client):
        content = b"provider storage content"
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-provider-upload')}?{qs}",
            {"file": _tar_file("provider_dl.tar", content)},
            format="multipart",
        )

        response = api_client.get(
            reverse("v1:files-provider-download"),
            {"function": self.FUNCTION, "provider": self.PROVIDER, "file": "provider_dl.tar"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert b"".join(response.streaming_content) == content

    def test_upload_then_delete(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-provider-upload')}?{qs}",
            {"file": _tar_file("provider_del.tar")},
            format="multipart",
        )

        del_qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER, "file": "provider_del.tar"})
        api_client.delete(f"{reverse('v1:files-provider-delete')}?{del_qs}")

        response = api_client.get(
            reverse("v1:files-provider-list"),
            {"function": self.FUNCTION, "provider": self.PROVIDER},
        )

        assert response.status_code == status.HTTP_200_OK
        assert "provider_del.tar" not in response.data["results"]

    def test_download_nonexistent_returns_404(self, api_client):
        response = api_client.get(
            reverse("v1:files-provider-download"),
            {"function": self.FUNCTION, "provider": self.PROVIDER, "file": "ghost.tar"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_nonexistent_returns_404(self, api_client):
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER, "file": "ghost.tar"})
        response = api_client.delete(f"{reverse('v1:files-provider-delete')}?{qs}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_upload_stores_file_in_cos(self, api_client, minio_s3):
        """Verify the file actually lands in the COS bucket."""
        content = b"provider cos verification"
        qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-provider-upload')}?{qs}",
            {"file": _tar_file("provider_cos_check.tar", content)},
            format="multipart",
        )

        # PROVIDER_STORAGE key structure: provider_name/function_title/filename
        response = minio_s3.get_object(Bucket="ray-test", Key="default/Program/provider_cos_check.tar")
        assert response["Body"].read() == content

    def test_user_and_provider_storage_are_isolated(self, api_client):
        """A file uploaded to user storage should not appear in provider storage."""
        user_qs = urlencode({"function": self.FUNCTION, "provider": self.PROVIDER})
        api_client.post(
            f"{reverse('v1:files-upload')}?{user_qs}",
            {"file": _tar_file("isolation_check.tar")},
            format="multipart",
        )

        provider_list = api_client.get(
            reverse("v1:files-provider-list"),
            {"function": self.FUNCTION, "provider": self.PROVIDER},
        )

        assert "isolation_check.tar" not in provider_list.data.get("results", [])
