"""Tests for RayResultStorage."""

import os

import pytest

from core.services.storage.result_storage_ray import RayResultStorage as ResultStorage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestRayResultStorage:
    """Tests for RayResultStorage path generation and file operations."""

    @pytest.fixture
    def job(self):
        program = TestUtils.create_program(program_title="myfun", author="user1")
        return TestUtils.create_job(author="user1", program=program)

    @pytest.fixture
    def provider_job(self):
        program = TestUtils.create_program(program_title="myfun", author="user1", provider="myprovider")
        return TestUtils.create_job(author="user1", program=program)

    def test_path_generation(self, tmp_path, settings, job):
        """User (artifact) function: path is {username}/results/."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=job)
        assert storage.results_directory == f"{tmp_path}/user1/results"
        assert os.path.exists(storage.results_directory)

    def test_path_generation_provider(self, tmp_path, settings, provider_job):
        """Provider (custom-image) function: path is provider-aware,
        {username}/{provider}/{title}/results/ — matching where the function writes
        results via the RESULTS_PATH env var."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=provider_job)
        assert storage.results_directory == f"{tmp_path}/user1/myprovider/myfun/results"
        assert os.path.exists(storage.results_directory)

    def test_save_and_get(self, tmp_path, settings, job):
        """Test saving and retrieving results (user function)."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=job)
        assert storage.get() is None
        storage.save("foo")
        assert storage.get() == "foo"
        storage.save("overwrite")
        assert storage.get() == "overwrite"

    def test_save_and_get_provider(self, tmp_path, settings, provider_job):
        """Save/get round-trips for a provider function (regression for the
        provider results path mismatch)."""
        settings.MEDIA_ROOT = str(tmp_path)
        storage = ResultStorage(job=provider_job)
        assert storage.get() is None
        storage.save("bar")
        assert storage.get() == "bar"
