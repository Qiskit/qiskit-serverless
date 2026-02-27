"""Tests for ArgumentsStorage service."""

import os
import tempfile

from django.test import TestCase

from core.services.storage.arguments_storage import ArgumentsStorage


class TestArgumentsStorage(TestCase):
    """Tests for ArgumentsStorage path generation and file operations."""

    def test_path_without_provider(self):
        """User job: path is {username}/arguments/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = ArgumentsStorage(username="user1", function_title="myfun")

        self.assertEqual(storage.sub_path, "user1/arguments")
        self.assertEqual(storage.absolute_path, f"{temp_dir}/user1/arguments")
        self.assertTrue(os.path.exists(storage.absolute_path))

    def test_path_with_provider(self):
        """Provider job: path is {username}/{provider}/{function}/arguments/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = ArgumentsStorage(
                username="user1",
                function_title="myfun",
                provider_name="provider1",
            )

        self.assertEqual(storage.sub_path, "user1/provider1/myfun/arguments")
        self.assertEqual(storage.absolute_path, f"{temp_dir}/user1/provider1/myfun/arguments")

    def test_save_and_get(self):
        """Test saving and retrieving arguments."""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = ArgumentsStorage(username="user1", function_title="myfun")

            # file not found returns None
            self.assertEqual(storage.get("id"), None)

            storage.save("id", "foo")
            self.assertEqual(storage.get("id"), "foo")

            storage.save("id", "overwrite")
            self.assertEqual(storage.get("id"), "overwrite")
