"""Unit tests for provider file use cases: list, download, upload, delete."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import Group, User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.exceptions.provider_not_found_exception import ProviderNotFoundException
from api.use_cases.files.provider_delete import FilesProviderDeleteUseCase
from api.use_cases.files.provider_download import FilesProviderDownloadUseCase
from api.use_cases.files.provider_list import FilesProviderListUseCase
from api.use_cases.files.provider_upload import FilesProviderUploadUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_PROVIDER_FILES_READ,
    PLATFORM_PERMISSION_PROVIDER_FILES_WRITE,
    Program,
    Provider,
)
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture()
def user():
    return User.objects.create_user(username="user")


@pytest.fixture()
def admin_user():
    return User.objects.create_user(username="admin")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture()
def provider_with_admin(provider, admin_user):
    g = Group.objects.create(name="my-provider-admin-group")
    admin_user.groups.add(g)
    provider.admin_groups.add(g)
    return provider


@pytest.fixture()
def function(provider, user):
    return Program.objects.create(title="my-function", author=user, provider=provider)


def _legacy():
    return FunctionAccessResult(use_legacy_authorization=True)


def _read_access():
    return create_function_access_result("my-provider", "my-function", {PLATFORM_PERMISSION_PROVIDER_FILES_READ})


def _write_access():
    return create_function_access_result("my-provider", "my-function", {PLATFORM_PERMISSION_PROVIDER_FILES_WRITE})


def _no_access():
    return FunctionAccessResult(use_legacy_authorization=False, functions=[])


class TestFilesProviderList:
    class TestLegacy:
        def test_admin_can_list_files(self, admin_user, provider_with_admin, function):
            with patch("api.use_cases.files.provider_list.FileStorage") as mock_storage:
                mock_storage.return_value.get_files.return_value = ["file1.txt"]
                result = FilesProviderListUseCase().execute(admin_user, "my-provider", "my-function", _legacy())
            assert result == ["file1.txt"]

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderListUseCase().execute(user, "my-provider", "my-function", _legacy())

        def test_unknown_provider_raises_provider_not_found(self, admin_user):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderListUseCase().execute(admin_user, "nonexistent", "my-function", _legacy())

        def test_unknown_function_raises_function_not_found(self, admin_user, provider_with_admin):
            with pytest.raises(FunctionNotFoundException):
                FilesProviderListUseCase().execute(admin_user, "my-provider", "ghost-function", _legacy())

    class TestRuntimeInstances:
        def test_read_permission_grants_access(self, user, provider, function):
            with patch("api.use_cases.files.provider_list.FileStorage") as mock_storage:
                mock_storage.return_value.get_files.return_value = ["file1.txt"]
                result = FilesProviderListUseCase().execute(user, "my-provider", "my-function", _read_access())
            assert result == ["file1.txt"]

        def test_no_permission_raises_provider_not_found(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderListUseCase().execute(user, "my-provider", "my-function", _no_access())

        def test_wrong_permission_raises_provider_not_found(self, user, provider, function):
            wrong = create_function_access_result("my-provider", "my-function", {"other.permission"})
            with pytest.raises(ProviderNotFoundException):
                FilesProviderListUseCase().execute(user, "my-provider", "my-function", wrong)


class TestFilesProviderDownload:
    class TestLegacy:
        def test_admin_can_download_file(self, admin_user, provider_with_admin, function):
            stream = (b"data" for _ in range(1))
            with patch("api.use_cases.files.provider_download.FileStorage") as mock_storage:
                mock_storage.return_value.get_file_stream.return_value = (stream, "text/plain", 4)
                result = FilesProviderDownloadUseCase().execute(
                    admin_user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )
            assert result is not None

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderDownloadUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )

        def test_unknown_function_raises_function_not_found(self, admin_user, provider_with_admin):
            with pytest.raises(FunctionNotFoundException):
                FilesProviderDownloadUseCase().execute(
                    admin_user, "my-provider", "ghost-function", "file.txt", accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_read_permission_grants_access(self, user, provider, function):
            stream = (b"data" for _ in range(1))
            with patch("api.use_cases.files.provider_download.FileStorage") as mock_storage:
                mock_storage.return_value.get_file_stream.return_value = (stream, "text/plain", 4)
                result = FilesProviderDownloadUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_read_access()
                )
            assert result is not None

        def test_no_permission_raises_provider_not_found(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderDownloadUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_no_access()
                )


class TestFilesProviderUpload:
    class TestLegacy:
        def test_admin_can_upload_file(self, admin_user, provider_with_admin, function):
            uploaded_file = MagicMock()
            with patch("api.use_cases.files.provider_upload.FileStorage") as mock_storage:
                mock_storage.return_value.upload_file.return_value = "path/to/file.txt"
                result = FilesProviderUploadUseCase().execute(
                    admin_user, "my-provider", "my-function", uploaded_file, accessible_functions=_legacy()
                )
            assert result == "path/to/file.txt"

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderUploadUseCase().execute(
                    user, "my-provider", "my-function", MagicMock(), accessible_functions=_legacy()
                )

        def test_unknown_function_raises_function_not_found(self, admin_user, provider_with_admin):
            with pytest.raises(FunctionNotFoundException):
                FilesProviderUploadUseCase().execute(
                    admin_user, "my-provider", "ghost-function", MagicMock(), accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_write_permission_grants_access(self, user, provider, function):
            uploaded_file = MagicMock()
            with patch("api.use_cases.files.provider_upload.FileStorage") as mock_storage:
                mock_storage.return_value.upload_file.return_value = "path/to/file.txt"
                result = FilesProviderUploadUseCase().execute(
                    user, "my-provider", "my-function", uploaded_file, accessible_functions=_write_access()
                )
            assert result == "path/to/file.txt"

        def test_no_permission_raises_provider_not_found(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderUploadUseCase().execute(
                    user, "my-provider", "my-function", MagicMock(), accessible_functions=_no_access()
                )

        def test_read_permission_is_not_enough_for_upload(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderUploadUseCase().execute(
                    user, "my-provider", "my-function", MagicMock(), accessible_functions=_read_access()
                )


class TestFilesProviderDelete:
    class TestLegacy:
        def test_admin_can_delete_file(self, admin_user, provider_with_admin, function):
            with patch("api.use_cases.files.provider_delete.FileStorage") as mock_storage:
                mock_storage.return_value.remove_file.return_value = True
                FilesProviderDeleteUseCase().execute(
                    admin_user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )

        def test_non_admin_raises_provider_not_found(self, user, provider_with_admin):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderDeleteUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )

        def test_unknown_function_raises_function_not_found(self, admin_user, provider_with_admin):
            with pytest.raises(FunctionNotFoundException):
                FilesProviderDeleteUseCase().execute(
                    admin_user, "my-provider", "ghost-function", "file.txt", accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_write_permission_grants_access(self, user, provider, function):
            with patch("api.use_cases.files.provider_delete.FileStorage") as mock_storage:
                mock_storage.return_value.remove_file.return_value = True
                FilesProviderDeleteUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_write_access()
                )

        def test_no_permission_raises_provider_not_found(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderDeleteUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_no_access()
                )

        def test_read_permission_is_not_enough_for_delete(self, user, provider, function):
            with pytest.raises(ProviderNotFoundException):
                FilesProviderDeleteUseCase().execute(
                    user, "my-provider", "my-function", "file.txt", accessible_functions=_read_access()
                )
