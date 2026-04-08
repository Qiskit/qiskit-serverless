"""Tests for ResultStorage service."""

import os

import pytest

from core.services.storage.result_storage import ResultStorage


class TestResultStorage:
    """Tests for ResultStorage path generation and file operations."""

    def test_path_generation(self, tmp_path, settings):
        """Test path is {username}/results/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(username="user1")
        assert storage.user_results_directory == f"{tmp_path}/user1/results"
        assert os.path.exists(storage.user_results_directory)

    def test_save_and_get(self, tmp_path, settings):
        """Test saving and retrieving results."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(username="user1")
        # file not found returns None
        assert storage.get("id") is None
        storage.save("id", "foo")
        assert storage.get("id") == "foo"
        storage.save("id", "overwrite")
        assert storage.get("id") == "overwrite"
