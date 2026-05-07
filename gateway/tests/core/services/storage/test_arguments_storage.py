"""Tests for ArgumentsStorage service."""

import os

import pytest

from core.services.storage.arguments_storage_ray import RayArgumentsStorage as ArgumentsStorage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestArgumentsStorage:
    """Tests for ArgumentsStorage path generation and file operations."""

    @pytest.fixture
    def program(self):
        return TestUtils.create_program(program_title="myfun", author="user1")

    @pytest.fixture
    def program_with_provider(self):
        return TestUtils.create_program(program_title="myfun", author="user1", provider="provider1")

    def test_path_without_provider(self, tmp_path, settings, program):
        """User job: path is {username}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(username="user1", function=program)

        assert storage.sub_path == "user1/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/arguments"
        assert os.path.exists(storage.absolute_path)

    def test_path_with_provider(self, tmp_path, settings, program_with_provider):
        """Provider job: path is {username}/{provider}/{function}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(username="user1", function=program_with_provider)

        assert storage.sub_path == "user1/provider1/myfun/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/provider1/myfun/arguments"

    def test_save_and_get(self, tmp_path, settings, program):
        """Test saving and retrieving arguments."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(username="user1", function=program)

        # file not found returns None
        assert storage.get("id") is None

        storage.save("id", "foo")
        assert storage.get("id") == "foo"

        storage.save("id", "overwrite")
        assert storage.get("id") == "overwrite"
