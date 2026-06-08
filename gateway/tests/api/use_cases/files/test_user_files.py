"""Unit tests for user file use cases: list, download, upload, delete."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import Group, Permission, User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.files.delete import FilesDeleteUseCase
from api.use_cases.files.download import FilesDownloadUseCase
from api.use_cases.files.list import FilesListUseCase
from api.use_cases.files.upload import FilesUploadUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_USER_FILES_READ,
    PLATFORM_PERMISSION_USER_FILES_WRITE,
    RUN_PROGRAM_PERMISSION,
    Program,
    Provider,
)
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture()
def author():
    return User.objects.create_user(username="author")


@pytest.fixture()
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture()
def provider():
    return Provider.objects.create(name="my-provider")


@pytest.fixture()
def function(provider, author):
    return Program.objects.create(title="my-function", author=author, provider=provider)


@pytest.fixture()
def user_function(author):
    return Program.objects.create(title="personal-function", author=author, provider=None)


@pytest.fixture()
def legacy_user_with_run_permission(provider, function):
    """User with run_program permission via Django groups (legacy fallback)."""
    user = User.objects.create_user(username="legacy-user")
    permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)
    group = Group.objects.create(name="legacy-run-group")
    group.permissions.add(permission)
    user.groups.add(group)
    function.instances.add(group)
    return user


def _legacy():
    return FunctionAccessResult(use_legacy_authorization=True)


def _read_access():
    return create_function_access_result("my-provider", "my-function", {PLATFORM_PERMISSION_USER_FILES_READ})


def _write_access():
    return create_function_access_result("my-provider", "my-function", {PLATFORM_PERMISSION_USER_FILES_WRITE})


def _no_access():
    return FunctionAccessResult(use_legacy_authorization=False, functions=[])


class TestFilesList:
    class TestLegacy:
        def test_user_with_run_permission_can_list_files(self, legacy_user_with_run_permission, function):
            with patch("api.use_cases.files.list.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_public_files.return_value = ["file1.txt"]
                mock_factory.return_value = mock_storage
                result = FilesListUseCase().execute(
                    legacy_user_with_run_permission,
                    "my-provider",
                    "my-function",
                    accessible_functions=_legacy(),
                )
            assert result == ["file1.txt"]

        def test_user_without_permission_raises_function_not_found(self, other_user, provider, function):
            with pytest.raises(FunctionNotFoundException):
                FilesListUseCase().execute(other_user, "my-provider", "my-function", accessible_functions=_legacy())

        def test_user_function_no_provider(self, author, user_function):
            with patch("api.use_cases.files.list.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_public_files.return_value = ["file1.txt"]
                mock_factory.return_value = mock_storage
                result = FilesListUseCase().execute(author, None, "personal-function", accessible_functions=_legacy())
            assert result == ["file1.txt"]

    class TestRuntimeInstances:
        def test_read_permission_grants_access(self, other_user, function):
            with patch("api.use_cases.files.list.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_public_files.return_value = ["file1.txt"]
                mock_factory.return_value = mock_storage
                result = FilesListUseCase().execute(
                    other_user, "my-provider", "my-function", accessible_functions=_read_access()
                )
            assert result == ["file1.txt"]

        def test_no_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesListUseCase().execute(other_user, "my-provider", "my-function", accessible_functions=_no_access())

        def test_wrong_permission_raises_function_not_found(self, other_user, function):
            wrong = create_function_access_result("my-provider", "my-function", {"other.permission"})
            with pytest.raises(FunctionNotFoundException):
                FilesListUseCase().execute(other_user, "my-provider", "my-function", accessible_functions=wrong)

        def test_user_function_no_provider_skips_client_check(self, author, user_function):
            with patch("api.use_cases.files.list.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_public_files.return_value = ["file1.txt"]
                mock_factory.return_value = mock_storage
                result = FilesListUseCase().execute(
                    author, None, "personal-function", accessible_functions=_no_access()
                )
            assert result == ["file1.txt"]


class TestFilesDownload:
    class TestLegacy:
        def test_user_with_run_permission_can_download(self, legacy_user_with_run_permission, function):
            stream = (b"data" for _ in range(1))
            with patch("api.use_cases.files.download.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_file_stream.return_value = (stream, "text/plain", 4)
                mock_factory.return_value = mock_storage
                result = FilesDownloadUseCase().execute(
                    legacy_user_with_run_permission,
                    "my-provider",
                    "my-function",
                    "file.txt",
                    accessible_functions=_legacy(),
                )
            assert result is not None

        def test_user_without_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesDownloadUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_read_permission_grants_access(self, other_user, function):
            stream = (b"data" for _ in range(1))
            with patch("api.use_cases.files.download.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.get_file_stream.return_value = (stream, "text/plain", 4)
                mock_factory.return_value = mock_storage
                result = FilesDownloadUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_read_access()
                )
            assert result is not None

        def test_no_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesDownloadUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_no_access()
                )


class TestFilesUpload:
    class TestLegacy:
        def test_user_with_run_permission_can_upload(self, legacy_user_with_run_permission, function):
            uploaded_file = MagicMock()
            with patch("api.use_cases.files.upload.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.upload_public_file.return_value = "path/to/file.txt"
                mock_factory.return_value = mock_storage
                result = FilesUploadUseCase().execute(
                    legacy_user_with_run_permission,
                    "my-provider",
                    "my-function",
                    uploaded_file,
                    accessible_functions=_legacy(),
                )
            assert result == "path/to/file.txt"

        def test_user_without_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesUploadUseCase().execute(
                    other_user, "my-provider", "my-function", MagicMock(), accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_write_permission_grants_access(self, other_user, function):
            uploaded_file = MagicMock()
            with patch("api.use_cases.files.upload.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.upload_public_file.return_value = "path/to/file.txt"
                mock_factory.return_value = mock_storage
                result = FilesUploadUseCase().execute(
                    other_user, "my-provider", "my-function", uploaded_file, accessible_functions=_write_access()
                )
            assert result == "path/to/file.txt"

        def test_no_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesUploadUseCase().execute(
                    other_user, "my-provider", "my-function", MagicMock(), accessible_functions=_no_access()
                )

        def test_read_permission_is_not_enough_for_upload(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesUploadUseCase().execute(
                    other_user, "my-provider", "my-function", MagicMock(), accessible_functions=_read_access()
                )


class TestFilesDelete:
    class TestLegacy:
        def test_user_with_run_permission_can_delete(self, legacy_user_with_run_permission, function):
            with patch("api.use_cases.files.delete.get_file_storage") as mock_factory:
                mock_storage = MagicMock()
                mock_storage.remove_file.return_value = True
                mock_factory.return_value = mock_storage
                FilesDeleteUseCase().execute(
                    legacy_user_with_run_permission,
                    "my-provider",
                    "my-function",
                    "file.txt",
                    accessible_functions=_legacy(),
                )

        def test_user_without_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesDeleteUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_legacy()
                )

    class TestRuntimeInstances:
        def test_write_permission_grants_access(self, other_user, function):
            with patch("api.use_cases.files.delete.get_file_storage") as mock_storage:
                mock_storage.return_value.remove_file.return_value = True
                FilesDeleteUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_write_access()
                )

        def test_no_permission_raises_function_not_found(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesDeleteUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_no_access()
                )

        def test_read_permission_is_not_enough_for_delete(self, other_user, function):
            with pytest.raises(FunctionNotFoundException):
                FilesDeleteUseCase().execute(
                    other_user, "my-provider", "my-function", "file.txt", accessible_functions=_read_access()
                )
