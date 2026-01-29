"""Tests for ResultStorage service."""

import os
import tempfile

from django.test import TestCase

from core.services.storage.result_storage import ResultStorage


class TestResultStorage(TestCase):
    """Tests for ResultStorage path generation and file operations."""

    def test_path_generation(self):
        """Test path is {username}/results/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = ResultStorage(username="user1")

        self.assertEqual(storage.user_results_directory, f"{temp_dir}/user1/results")
        self.assertTrue(os.path.exists(storage.user_results_directory))

    def test_save_and_get(self):
        """Test saving and retrieving results."""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = ResultStorage(username="user1")

        # file not found returns None
        self.assertEqual(storage.get("id"), None)

        storage.save("id", "foo")
        self.assertEqual(storage.get("id"), "foo")

        storage.save("id", "overwrite")
        self.assertEqual(storage.get("id"), "overwrite")
