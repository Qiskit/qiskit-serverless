"""Tests for ArgumentsStorage service."""

import os

from core.services.storage.arguments_storage import ArgumentsStorage


class TestArgumentsStorage:
    """Tests for ArgumentsStorage path generation and file operations."""

    def test_path_without_provider(self, tmp_path, settings):
        """User job: path is {username}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(username="user1", function_title="myfun")

        assert storage.sub_path == "user1/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/arguments"
        assert os.path.exists(storage.absolute_path)

    def test_path_with_provider(self, tmp_path, settings):
        """Provider job: path is {username}/{provider}/{function}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(
            username="user1",
            function_title="myfun",
            provider_name="provider1",
        )

        assert storage.sub_path == "user1/provider1/myfun/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/provider1/myfun/arguments"

    def test_save_and_get(self, tmp_path, settings):
        """Test saving and retrieving arguments."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(username="user1", function_title="myfun")

        # file not found returns None
        assert storage.get("id") is None

        storage.save("id", "foo")
        assert storage.get("id") == "foo"

        storage.save("id", "overwrite")
        assert storage.get("id") == "overwrite"
