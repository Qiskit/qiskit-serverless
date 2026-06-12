"""Tests for FileStorageFleets."""

from unittest.mock import MagicMock, patch
from io import BytesIO

import pytest
from ibm_botocore.exceptions import ClientError
from django.core.files.base import ContentFile

from core.models import Program
from core.services.storage.file_storage_fleets import FileStorageFleets
from tests.utils import TestUtils

_COS_MODULE = "core.services.storage.file_storage_fleets.get_cos_client"


def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": ""}}, "GetObject")


@pytest.mark.django_db
class TestFileStorageFleets:
    """Tests for FileStorageFleets."""

    @pytest.fixture
    def ce_project(self):
        return TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )

    @pytest.fixture
    def function(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            runner=Program.FLEETS,
        )
        program.code_engine_project = ce_project
        program.save()
        return program

    @pytest.fixture
    def function_with_provider(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
        )
        program.code_engine_project = ce_project
        program.save()
        return program

    # ── initialization ─────────────────────────────────────────────────────────

    def test_initialization_succeeds(self, function):
        """FileStorageFleets initializes with valid function."""
        storage = FileStorageFleets("alice", function)
        assert storage._user_id == "alice"
        assert storage._function_id == str(function.id)
        assert storage._user_bucket == "user-bucket"

    def test_initialization_with_no_project_raises(self):
        """ValueError raised when function has no CodeEngineProject."""
        program = TestUtils.create_program(program_title="orphan", author="bob", runner=Program.FLEETS)
        with pytest.raises(ValueError, match="no CodeEngineProject"):
            FileStorageFleets("bob", program)

    def test_provider_bucket_is_none_for_custom_function(self, function):
        """_provider_bucket is None when program has no provider."""
        storage = FileStorageFleets("alice", function)
        assert storage._provider_bucket is None

    def test_provider_bucket_is_set_for_provider_function(self, function_with_provider):
        """_provider_bucket is set when program has a provider."""
        storage = FileStorageFleets("alice", function_with_provider)
        assert storage._provider_bucket == "provider-bucket"

    # ── get_public_files ───────────────────────────────────────────────────────

    def test_get_public_files_returns_list(self, function):
        """get_public_files() returns bare file names stripped of the COS key prefix."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.list_keys.return_value = [
            "users/alice/custom_functions/my-program/data/file1.txt",
            "users/alice/custom_functions/my-program/data/file2.txt",
        ]

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_files()

        assert result == ["file1.txt", "file2.txt"]
        mock_cos.list_keys.assert_called_once_with(
            bucket_name="user-bucket",
            prefix=storage._public_folder_key,
        )

    def test_get_public_files_returns_empty_on_not_found(self, function):
        """get_public_files() returns empty list when no files found."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.list_keys.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_files()

        assert result == []

    # ── get_private_files ──────────────────────────────────────────────────────

    def test_get_private_files_returns_list(self, function_with_provider):
        """get_private_files() returns bare file names stripped of the COS key prefix."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.list_keys.return_value = [
            "providers/good-partner/my-program/data/private1.txt",
            "providers/good-partner/my-program/data/private2.txt",
        ]

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_files()

        assert result == ["private1.txt", "private2.txt"]
        mock_cos.list_keys.assert_called_once_with(
            bucket_name="provider-bucket",
            prefix=storage._private_folder_key,
        )

    def test_get_private_files_returns_none_for_custom_function(self, function):
        """get_private_files() returns None for non-provider functions."""
        storage = FileStorageFleets("alice", function)
        assert storage.get_private_files() is None

    def test_get_private_files_returns_none_on_not_found(self, function_with_provider):
        """get_private_files() returns None when no files found."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.list_keys.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_files()

        assert result is None

    # ── get_public_file ────────────────────────────────────────────────────────

    def test_get_public_file_returns_tuple(self, function):
        """get_public_file() returns (FileWrapper, content_type, size) tuple."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"file content"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_file("test.txt")

        assert result is not None
        wrapper, content_type, size = result
        assert content_type == "application/octet-stream"
        assert size == 12

    def test_get_public_file_returns_none_on_not_found(self, function):
        """get_public_file() returns None when file not found."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_file("missing.txt")

        assert result is None

    # ── get_private_file ───────────────────────────────────────────────────────

    def test_get_private_file_returns_tuple(self, function_with_provider):
        """get_private_file() returns (FileWrapper, content_type, size) tuple."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"private file content"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_file("private.txt")

        assert result is not None
        wrapper, content_type, size = result
        assert content_type == "application/octet-stream"
        assert size == 20

    def test_get_private_file_returns_none_for_custom_function(self, function):
        """get_private_file() returns None for non-provider functions."""
        storage = FileStorageFleets("alice", function)
        result = storage.get_private_file("test.txt")
        assert result is None

    def test_get_private_file_returns_none_on_not_found(self, function_with_provider):
        """get_private_file() returns None when file not found."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_file("missing.txt")

        assert result is None

    # ── get_public_file_stream ─────────────────────────────────────────────────

    def test_get_public_file_stream_returns_generator(self, function):
        """get_public_file_stream() returns (generator, content_type, size) tuple."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"chunk1chunk2"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_file_stream("test.txt", chunk_size=6)

        assert result is not None
        generator, content_type, size = result
        assert content_type == "application/octet-stream"
        assert size == 12
        chunks = list(generator)
        assert chunks == [b"chunk1", b"chunk2"]

    def test_get_public_file_stream_returns_none_on_not_found(self, function):
        """get_public_file_stream() returns None when file not found."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_file_stream("missing.txt")

        assert result is None

    # ── get_private_file_stream ────────────────────────────────────────────────

    def test_get_private_file_stream_returns_generator(self, function_with_provider):
        """get_private_file_stream() returns (generator, content_type, size) tuple."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"privchunk1privchunk2"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_file_stream("private.pdf", chunk_size=10)

        assert result is not None
        generator, content_type, size = result
        assert content_type == "application/octet-stream"
        assert size == 20
        chunks = list(generator)
        assert chunks == [b"privchunk1", b"privchunk2"]

    def test_get_private_file_stream_returns_none_for_custom_function(self, function):
        """get_private_file_stream() returns None for non-provider functions."""
        storage = FileStorageFleets("alice", function)
        result = storage.get_private_file_stream("test.txt")
        assert result is None

    def test_get_private_file_stream_returns_none_on_not_found(self, function_with_provider):
        """get_private_file_stream() returns None when file not found."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_file_stream("missing.txt")

        assert result is None

    # ── upload_public_file ─────────────────────────────────────────────────────

    def test_upload_public_file_returns_key(self, function):
        """upload_public_file() uploads file and returns key."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        file = ContentFile(b"test content", name="test.txt")

        with patch(_COS_MODULE, return_value=mock_cos):
            key = storage.upload_public_file(file)

        assert "test.txt" == key
        mock_cos.upload_fileobj.assert_called_once()

    def test_upload_public_file_raises_on_error(self, function):
        """upload_public_file() raises on COS error."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.upload_fileobj.side_effect = _make_client_error("AccessDenied")
        file = ContentFile(b"test content", name="test.txt")

        with patch(_COS_MODULE, return_value=mock_cos):
            with pytest.raises(ClientError):
                storage.upload_public_file(file)

    # ── upload_private_file ────────────────────────────────────────────────────

    def test_upload_private_file_returns_key(self, function_with_provider):
        """upload_private_file() uploads file and returns key."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        file = ContentFile(b"private content", name="private.txt")

        with patch(_COS_MODULE, return_value=mock_cos):
            key = storage.upload_private_file(file)

        assert "private.txt" == key
        mock_cos.upload_fileobj.assert_called_once()

    def test_upload_private_file_raises_for_custom_function(self, function):
        """upload_private_file() raises for non-provider functions."""
        storage = FileStorageFleets("alice", function)
        file = ContentFile(b"content", name="test.txt")

        with pytest.raises(ValueError, match="Private folder key"):
            storage.upload_private_file(file)

    def test_upload_private_file_raises_on_error(self, function_with_provider):
        """upload_private_file() raises on COS error."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.upload_fileobj.side_effect = _make_client_error("AccessDenied")
        file = ContentFile(b"private content", name="private.txt")

        with patch(_COS_MODULE, return_value=mock_cos):
            with pytest.raises(ClientError):
                storage.upload_private_file(file)

    # ── remove_public_file ─────────────────────────────────────────────────────

    def test_remove_public_file_returns_true(self, function):
        """remove_public_file() returns True on success."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.remove_public_file("test.txt")

        assert result is True
        mock_cos.delete_object.assert_called_once()

    def test_remove_public_file_returns_false_on_error(self, function):
        """remove_public_file() returns False on COS error."""
        storage = FileStorageFleets("alice", function)
        mock_cos = MagicMock()
        mock_cos.delete_object.side_effect = _make_client_error("AccessDenied")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.remove_public_file("test.txt")

        assert result is False

    # ── remove_private_file ────────────────────────────────────────────────────

    def test_remove_private_file_returns_true(self, function_with_provider):
        """remove_private_file() returns True on success."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.remove_private_file("private.txt")

        assert result is True
        mock_cos.delete_object.assert_called_once()

    def test_remove_private_file_returns_false_for_custom_function(self, function):
        """remove_private_file() returns False for non-provider functions."""
        storage = FileStorageFleets("alice", function)
        result = storage.remove_private_file("test.txt")
        assert result is False

    def test_remove_private_file_returns_false_on_error(self, function_with_provider):
        """remove_private_file() returns False on COS error."""
        storage = FileStorageFleets("alice", function_with_provider)
        mock_cos = MagicMock()
        mock_cos.delete_object.side_effect = _make_client_error("AccessDenied")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.remove_private_file("test.txt")

        assert result is False
