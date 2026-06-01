"""Tests for FileStorage service."""

import os
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.services.storage import get_file_storage
from core.models import Program


def create_function(title, provider_name=None, runner=Program.RAY):
    mock_function = MagicMock()
    mock_function.title = title
    mock_function.runner = runner
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


def test_public_storage_without_provider(tmp_path, settings, function_without_provider):
    """User public storage without provider: path is {username}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_without_provider,
    )

    # Upload a public file
    file_content = b"public file content"
    uploaded_file = SimpleUploadedFile("public.txt", file_content)
    path = storage.upload_public_file(uploaded_file)
    assert os.path.exists(path)

    # Get public file
    file_wrapper, file_type, size = storage.get_public_file("public.txt")
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(file_wrapper) == file_content

    # List public files
    assert storage.get_public_files() == ["public.txt"]

    # Remove public file
    assert storage.remove_public_file("public.txt")
    assert not os.path.exists(path)
    assert storage.get_public_files() == []


def test_public_storage_with_provider(tmp_path, settings, function_with_provider):
    """User public storage with provider: path is {username}/{provider}/{function}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_with_provider,
    )

    # Upload a public file
    file_content = b"user public file"
    uploaded_file = SimpleUploadedFile("user_file.txt", file_content)
    path = storage.upload_public_file(uploaded_file)
    assert os.path.exists(path)

    # List public files
    assert storage.get_public_files() == ["user_file.txt"]

    # Remove public file
    assert storage.remove_public_file("user_file.txt")
    assert not os.path.exists(path)


def test_private_storage_with_provider(tmp_path, settings, function_with_provider):
    """Provider private storage (provider view): path is {provider}/{function}/"""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_with_provider,
    )

    # Upload a private file
    file_content = b"provider private file"
    uploaded_file = SimpleUploadedFile("private.txt", file_content)
    path = storage.upload_private_file(uploaded_file)
    assert os.path.exists(path)

    # Get private file
    file_wrapper, file_type, size = storage.get_private_file("private.txt")
    assert file_type == "text/plain" and size == len(file_content)
    assert b"".join(file_wrapper) == file_content

    # List private files
    assert storage.get_private_files() == ["private.txt"]

    # Remove private file
    assert storage.remove_private_file("private.txt")
    assert not os.path.exists(path)
    assert storage.get_private_files() == []


def test_public_file_stream_yields_correct_content(tmp_path, settings, function_with_provider):
    """get_public_file_stream yields the exact file bytes across all chunks."""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_with_provider,
    )

    file_content = b"hello serverless team"
    uploaded_file = SimpleUploadedFile("data.txt", file_content)
    storage.upload_public_file(uploaded_file)

    generator, file_type, file_size = storage.get_public_file_stream("data.txt", 2)
    assert file_type == "text/plain"
    assert file_size == len(file_content)
    received = b"".join(generator)
    assert received == file_content


def test_private_file_stream_yields_correct_content(tmp_path, settings, function_with_provider):
    """get_private_file_stream yields the exact file bytes across all chunks."""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_with_provider,
    )

    file_content = b"hello provider team"
    uploaded_file = SimpleUploadedFile("provider_data.txt", file_content)
    storage.upload_private_file(uploaded_file)

    generator, file_type, file_size = storage.get_private_file_stream("provider_data.txt", 2)
    assert file_type == "text/plain"
    assert file_size == len(file_content)
    received = b"".join(generator)
    assert received == file_content


def test_public_and_private_storage_independent(tmp_path, settings, function_with_provider):
    """Public and private storage are independent."""
    settings.MEDIA_ROOT = str(tmp_path)
    storage = get_file_storage(
        username="user1",
        function=function_with_provider,
    )

    # Upload files to both public and private storage
    public_content = b"public content"
    private_content = b"private content"

    public_file = SimpleUploadedFile("file.txt", public_content)
    private_file = SimpleUploadedFile("file.txt", private_content)

    storage.upload_public_file(public_file)
    storage.upload_private_file(private_file)

    # Verify both files exist in their respective locations
    assert storage.get_public_files() == ["file.txt"]
    assert storage.get_private_files() == ["file.txt"]

    # Verify content is different
    public_wrapper, _, _ = storage.get_public_file("file.txt")
    private_wrapper, _, _ = storage.get_private_file("file.txt")

    public_data = b"".join(public_wrapper)
    private_data = b"".join(private_wrapper)

    assert public_data == public_content
    assert private_data == private_content
    assert public_data != private_data

    # Remove public file only
    storage.remove_public_file("file.txt")
    assert storage.get_public_files() == []
    assert storage.get_private_files() == ["file.txt"]
