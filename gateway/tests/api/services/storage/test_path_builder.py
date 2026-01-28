"""Tests for PathBuilder service."""

import os
import tempfile

from django.test import TestCase

from api.services.storage.path_builder import PathBuilder, StoragePath


class TestPathBuilder(TestCase):
    """Tests for PathBuilder path generation."""

    def test_get_user_path_without_provider(self):
        """User path without provider: {username}/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_user_path(
                username="user1",
                function_title="myfun",
                provider_name=None,
            )

        self.assertIsInstance(result, StoragePath)
        self.assertEqual(result.sub_path, "user1")
        self.assertEqual(result.absolute_path, f"{temp_dir}/user1")
        self.assertTrue(os.path.exists(result.absolute_path))

    def test_get_user_path_with_provider(self):
        """User path with provider: {username}/{provider}/{function}/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_user_path(
                username="user1",
                function_title="myfun",
                provider_name="provider1",
            )

        self.assertIsInstance(result, StoragePath)
        self.assertEqual(result.sub_path, "user1/provider1/myfun")
        self.assertEqual(result.absolute_path, f"{temp_dir}/user1/provider1/myfun")
        self.assertTrue(os.path.exists(result.absolute_path))

    def test_get_user_path_with_extra_sub_path(self):
        """User path with extra_sub_path: {username}/{extra}/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_user_path(
                username="user1",
                function_title="myfun",
                provider_name=None,
                extra_sub_path="subdir",
            )

        self.assertIsInstance(result, StoragePath)
        self.assertEqual(result.sub_path, "user1/subdir")
        self.assertEqual(result.absolute_path, f"{temp_dir}/user1/subdir")
        self.assertTrue(os.path.exists(result.absolute_path))

    def test_get_provider_path(self):
        """Provider path: {provider}/{function}/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_provider_path(
                function_title="myfun",
                provider_name="provider1",
            )

        self.assertIsInstance(result, StoragePath)
        self.assertEqual(result.sub_path, "provider1/myfun")
        self.assertEqual(result.absolute_path, f"{temp_dir}/provider1/myfun")
        self.assertTrue(os.path.exists(result.absolute_path))

    def test_get_provider_path_with_extra_sub_path(self):
        """Provider path with extra_sub_path: {provider}/{function}/{extra}/"""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_provider_path(
                function_title="myfun",
                provider_name="provider1",
                extra_sub_path="subdir",
            )

        self.assertIsInstance(result, StoragePath)
        self.assertEqual(result.sub_path, "provider1/myfun/subdir")
        self.assertEqual(result.absolute_path, f"{temp_dir}/provider1/myfun/subdir")
        self.assertTrue(os.path.exists(result.absolute_path))

    def test_storage_path_is_namedtuple(self):
        """StoragePath should be immutable and accessible by name."""
        temp_dir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=temp_dir):
            result = PathBuilder.get_user_path(
                username="user1",
                function_title="myfun",
                provider_name=None,
            )

        # Access by index (tuple behavior)
        self.assertEqual(result[0], result.sub_path)
        self.assertEqual(result[1], result.absolute_path)

        # Unpacking
        sub_path, absolute_path = result
        self.assertEqual(sub_path, "user1")
        self.assertEqual(absolute_path, f"{temp_dir}/user1")
