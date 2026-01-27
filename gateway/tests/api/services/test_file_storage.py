"""Tests for FileStorage service."""

import os
import tempfile
from unittest.mock import MagicMock

from django.test import TestCase

from api.services.file_storage import FileStorage
from api.services.storage.enums.working_dir import WorkingDir


def create_function(title, provider_name=None):
    mock_function = MagicMock()
    mock_function.title = title
    if provider_name:
        mock_function.provider = MagicMock()
        mock_function.provider.name = provider_name
    else:
        mock_function.provider = None
    return mock_function


class TestFileStorage(TestCase):
    """Tests for FileStorage path generation."""

    def test_user_storage_without_provider(self):
        """User job: path is {username}/"""
        mock_function = create_function("x")

        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = FileStorage(
                username="user1",
                working_dir=WorkingDir.USER_STORAGE,
                function=mock_function,
            )

        self.assertEqual(storage.sub_path, "user1")
        self.assertEqual(storage.absolute_path, f"{temp_dir}/user1")
        self.assertTrue(os.path.exists(storage.absolute_path))

    def test_user_storage_with_provider(self):
        """Provider job (user view): path is {username}/{provider}/{function}/"""
        mock_function = create_function("myfun", "provider1")

        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            storage = FileStorage(
                username="user1",
                working_dir=WorkingDir.USER_STORAGE,
                function=mock_function,
            )

        self.assertEqual(storage.sub_path, "user1/provider1/myfun")
        self.assertEqual(storage.absolute_path, f"{temp_dir}/user1/provider1/myfun")
        self.assertTrue(os.path.exists(storage.absolute_path))

    def test_provider_storage(self):
        """Provider job (provider view): path is {provider}/{function}/"""
        temp_dir = tempfile.mkdtemp()
        mock_function = create_function("myfun", "provider1")

        with self.settings(MEDIA_ROOT=temp_dir):
            storage = FileStorage(
                username="user1",
                working_dir=WorkingDir.PROVIDER_STORAGE,
                function=mock_function,
            )

        self.assertEqual(storage.sub_path, "provider1/myfun")
        self.assertEqual(storage.absolute_path, f"{temp_dir}/provider1/myfun")
        self.assertTrue(os.path.exists(storage.absolute_path))
