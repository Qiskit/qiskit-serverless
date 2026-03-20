"""Tests for LogsStorage."""

import os

import pytest
from unittest.mock import Mock

from core.services.storage.logs_storage import LogsStorage


class TestLogsStorage:
    """Tests for LogsStorage."""

    @pytest.fixture(autouse=True)
    def media_root(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        self.tmp_path = tmp_path

    def _create_job(
        self,
        author_username,
        provider=None,
        job_id="test-job-id",
        function_title="func1",
    ):
        """Create a mock job for testing."""
        job = Mock()
        job.id = job_id
        job.author = Mock()
        job.author.username = author_username
        job.program = Mock()
        job.program.title = function_title
        if provider:
            job.program.provider = Mock()
            job.program.provider.name = provider
        else:
            job.program.provider = None
        return job

    def test_get_private_logs_not_allowed_for_user_job(self):
        """get_private_logs is not allowed for user jobs."""
        job = self._create_job("auth1", provider=None)

        with pytest.raises(RuntimeError):
            LogsStorage(job).get_private_logs()

    def test_save_private_logs_not_allowed_for_user_job(self):
        """save_private_logs is not allowed for user jobs."""
        job = self._create_job("auth1", provider=None)

        with pytest.raises(RuntimeError):
            LogsStorage(job).save_private_logs("some logs")

    def test_get_public_logs_returns_none_if_not_found(self):
        """get_public_logs returns None if file doesn't exist."""
        job = self._create_job("auth1", job_id="nonexistent")
        storage = LogsStorage(job)
        logs = storage.get_public_logs()

        assert logs is None

    def test_get_private_logs_returns_none_if_not_found(self):
        """get_public_logs returns None if file doesn't exist."""
        job = self._create_job("auth1", provider="prov1", job_id="nonexistent")
        storage = LogsStorage(job)
        logs = storage.get_private_logs()

        assert logs is None

    def test_save_and_get_public_logs_user_job(self):
        """Test saving and retrieving public logs for a user job."""
        job = self._create_job("auth1", provider=None, job_id="job-123")
        expected_path = os.path.join(str(self.tmp_path), "auth1", "logs", "job-123.log")
        storage = LogsStorage(job)
        storage.save_public_logs("test log content")
        logs = storage.get_public_logs()

        assert logs == "test log content"
        assert os.path.exists(expected_path)

    def test_save_and_get_public_logs_provider_job(self, tmp_path, settings):
        """Test saving and retrieving public logs for a provider job."""
        settings.MEDIA_ROOT = str(tmp_path)
        job = self._create_job("auth1", provider="prov1", job_id="id")
        path = os.path.join(str(tmp_path), "auth1", "prov1", "func1", "logs", "id.log")
        storage = LogsStorage(job)
        storage.save_public_logs("public log content")
        logs = storage.get_public_logs()

        assert logs == "public log content"
        assert os.path.exists(path)

    def test_save_and_get_private_logs_provider_job(self, tmp_path, settings):
        """Test saving and retrieving private logs for a provider job."""
        settings.MEDIA_ROOT = str(tmp_path)
        job = self._create_job("auth1", provider="prov1", job_id="id")
        expected_path = os.path.join(str(tmp_path), "prov1", "func1", "logs", "id.log")
        storage = LogsStorage(job)
        storage.save_private_logs("private log content")
        logs = storage.get_private_logs()

        assert logs == "private log content"
        assert os.path.exists(expected_path)
