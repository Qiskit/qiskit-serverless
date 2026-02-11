"""Tests for PathBuilder path generation."""

from django.test import TestCase

from api.services.storage.path_builder import PathBuilder
from api.services.storage.enums.working_dir import WorkingDir


class TestPathBuilder(TestCase):
    """Tests for PathBuilder path generation."""

    def test_user_storage_without_provider(self):
        """User job: path is {username}/logs/"""
        path = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username="user1",
            function_title="my_function",
            provider_name=None,
            extra_sub_path="logs",
        )
        self.assertEqual(path, "user1/logs")

    def test_user_storage_with_provider(self):
        """Provider job (user view): path is {username}/{provider}/{function}/logs/"""
        path = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username="user1",
            function_title="my_function",
            provider_name="provider1",
            extra_sub_path="logs",
        )
        self.assertEqual(path, "user1/provider1/my_function/logs")

    def test_provider_storage(self):
        """Provider job (provider view): path is {provider}/{function}/logs/"""
        path = PathBuilder.sub_path(
            working_dir=WorkingDir.PROVIDER_STORAGE,
            username="user1",  # ignored for PROVIDER_STORAGE
            function_title="my_function",
            provider_name="provider1",
            extra_sub_path="logs",
        )
        self.assertEqual(path, "provider1/my_function/logs")

    def test_user_storage_without_extra_sub_path(self):
        """User storage without extra sub path."""
        path = PathBuilder.sub_path(
            working_dir=WorkingDir.USER_STORAGE,
            username="user1",
            function_title="my_function",
            provider_name=None,
            extra_sub_path=None,
        )
        self.assertEqual(path, "user1")

    def test_provider_storage_without_extra_sub_path(self):
        """Provider storage without extra sub path."""
        path = PathBuilder.sub_path(
            working_dir=WorkingDir.PROVIDER_STORAGE,
            username="user1",
            function_title="my_function",
            provider_name="provider1",
            extra_sub_path=None,
        )
        self.assertEqual(path, "provider1/my_function")
