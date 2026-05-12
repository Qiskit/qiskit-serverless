"""Tests for ArgumentsStorage service."""

import os

import pytest

from core.services.storage.arguments_storage_ray import RayArgumentsStorage as ArgumentsStorage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestArgumentsStorage:
    """Tests for ArgumentsStorage path generation and file operations."""

    @pytest.fixture
    def job(self):
        program = TestUtils.create_program(program_title="myfun", author="user1")
        return TestUtils.create_job(author="user1", program=program)

    @pytest.fixture
    def job_with_provider(self):
        program = TestUtils.create_program(program_title="myfun", author="user1", provider="provider1")
        return TestUtils.create_job(author="user1", program=program)

    def test_path_without_provider(self, tmp_path, settings, job):
        """User job: path is {username}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(job=job)

        assert storage.sub_path == "user1/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/arguments"
        assert os.path.exists(storage.absolute_path)

    def test_path_with_provider(self, tmp_path, settings, job_with_provider):
        """Provider job: path is {username}/{provider}/{function}/arguments/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(job=job_with_provider)

        assert storage.sub_path == "user1/provider1/myfun/arguments"
        assert storage.absolute_path == f"{tmp_path}/user1/provider1/myfun/arguments"

    def test_save_and_get(self, tmp_path, settings, job):
        """Test saving and retrieving arguments."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ArgumentsStorage(job=job)

        # file not found returns None
        assert storage.get() is None

        storage.save("foo")
        assert storage.get() == "foo"

        storage.save("overwrite")
        assert storage.get() == "overwrite"
