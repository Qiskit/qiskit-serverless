"""Tests for FileStorage service."""

from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.services.storage.file_storage import FileStorage
from core.services.storage.enums.working_dir import WorkingDir


def _function(title, provider_name=None):
    mock_function = MagicMock()
    mock_function.title = title
    if provider_name:
        mock_function.provider = MagicMock()
        mock_function.provider.name = provider_name
    else:
        mock_function.provider = None
    return mock_function


@pytest.fixture
def function_without_provider():
    return _function("x")


@pytest.fixture
def function_with_provider():
    return _function("myfun", "provider1")


def test_user_storage_without_provider(mock_cos, function_without_provider):
    """User job: key prefix is username/"""
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.USER_STORAGE,
        function=function_without_provider,
        cos=mock_cos,
    )
    assert storage.sub_path == "user1"


def test_user_storage_with_provider(mock_cos, function_with_provider):
    """Provider job (user view): key prefix is username/provider/function/"""
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.USER_STORAGE,
        function=function_with_provider,
        cos=mock_cos,
    )
    assert storage.sub_path == "user1/provider1/myfun"


def test_provider_storage(mock_cos, function_with_provider):
    """Provider job (provider view): key prefix is provider/function/"""
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.PROVIDER_STORAGE,
        function=function_with_provider,
        cos=mock_cos,
    )
    assert storage.sub_path == "provider1/myfun"

    file_content = b"functions are cool"
    uploaded_file = SimpleUploadedFile("test.txt", file_content)
    storage.upload_file(uploaded_file)

    file_wrapper, file_type, size = storage.get_file("test.txt")
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(file_wrapper) == file_content

    generator, file_type, size = storage.get_file_stream("test.txt", 2)
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(generator) == file_content

    assert storage.get_files() == ["test.txt"]

    assert storage.remove_file("test.txt")
    assert storage.get_files() == []


def test_get_file_stream_yields_correct_content(mock_cos, function_with_provider):
    """get_file_stream yields exact file bytes across all chunks."""
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.PROVIDER_STORAGE,
        function=function_with_provider,
        cos=mock_cos,
    )

    file_content = b"hello serverless team"
    uploaded_file = SimpleUploadedFile("data.txt", file_content)
    storage.upload_file(uploaded_file)

    generator, file_type, file_size = storage.get_file_stream("data.txt", 2)
    assert file_type == "text/plain"
    assert file_size == len(file_content)
    assert b"".join(generator) == file_content
