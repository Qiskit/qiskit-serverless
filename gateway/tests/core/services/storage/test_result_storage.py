"""Tests for RayResultStorage."""

import os

import pytest

from core.services.storage.result_storage_ray import RayResultStorage as ResultStorage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestResultStorage:
    """Tests for RayResultStorage path generation and file operations."""

    @pytest.fixture
    def job(self):
        program = TestUtils.create_program(program_title="myfun", author="user1")
        return TestUtils.create_job(author="user1", program=program)

    def test_path_generation(self, tmp_path, settings, job):
        """Test path is {username}/results/"""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=job)
        assert storage.user_results_directory == f"{tmp_path}/user1/results"
        assert os.path.exists(storage.user_results_directory)

    def test_save_and_get(self, tmp_path, settings, job):
        """Test saving and retrieving results."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=job)
        assert storage.get() is None
        storage.save("foo")
        assert storage.get() == "foo"
        storage.save("overwrite")
        assert storage.get() == "overwrite"
