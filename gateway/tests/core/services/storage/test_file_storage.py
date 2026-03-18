"""Tests for FileStorage service."""

import os
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.services.storage.file_storage import FileStorage
from core.services.storage.enums.working_dir import WorkingDir


def create_function(title, provider_name=None):
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
    return create_function("x")


@pytest.fixture
def function_with_provider():
    return create_function("myfun", "provider1")


def test_user_storage_without_provider(tmp_path, settings, function_without_provider):
    """User job: path is {username}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.USER_STORAGE,
        function=function_without_provider,
    )

    assert storage.sub_path == "user1"
    assert storage.absolute_path == f"{tmp_path}/user1"
    assert os.path.exists(storage.absolute_path)


def test_user_storage_with_provider(tmp_path, settings, function_with_provider):
    """Provider job (user view): path is {username}/{provider}/{function}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.USER_STORAGE,
        function=function_with_provider,
    )

    assert storage.sub_path == "user1/provider1/myfun"
    assert storage.absolute_path == f"{tmp_path}/user1/provider1/myfun"
    assert os.path.exists(storage.absolute_path)


def test_provider_storage(tmp_path, settings, function_with_provider):
    """Provider job (provider view): path is {provider}/{function}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.PROVIDER_STORAGE,
        function=function_with_provider,
    )

    assert storage.sub_path == "provider1/myfun"
    assert storage.absolute_path == f"{tmp_path}/provider1/myfun"
    assert os.path.exists(storage.absolute_path)

    # Upload a file
    file_content = b"functions are cool"
    uploaded_file = SimpleUploadedFile("test.txt", file_content)
    path = storage.upload_file(uploaded_file)
    assert os.path.exists(path)

    file_wrapper, file_type, size = storage.get_file("test.txt")
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(file_wrapper) == file_content

    generator, file_type, size = storage.get_file_stream("test.txt", 2)
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(generator) == file_content

    # List one file
    assert storage.get_files() == ["test.txt"]

    # Remove the file
    assert storage.remove_file("test.txt")
    assert not os.path.exists(path)

    # Now the list has no files
    assert storage.get_files() == []


def test_get_file_stream_yields_correct_content(tmp_path, settings, function_with_provider):
    """get_file_stream yields the exact file bytes across all chunks."""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = FileStorage(
        username="user1",
        working_dir=WorkingDir.PROVIDER_STORAGE,
        function=function_with_provider,
    )

    file_content = b"hello serverless team"
    uploaded_file = SimpleUploadedFile("data.txt", file_content)
    storage.upload_file(uploaded_file)

    generator, file_type, file_size = storage.get_file_stream("data.txt", 2)
    assert file_type == "text/plain"
    assert file_size == len(file_content)
    received = b"".join(generator)
    assert received == file_content
