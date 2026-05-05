"""Tests for LogsStorage."""

import pytest
from unittest.mock import Mock

from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from core.services.storage.logs_storage import LogsStorage


def _mock_job(username, provider=None, job_id="test-job-id", function_title="func1"):
    job = Mock()
    job.id = job_id
    job.author = Mock()
    job.author.username = username
    job.program = Mock()
    job.program.title = function_title
    if provider:
        job.program.provider = Mock()
        job.program.provider.name = provider
    else:
        job.program.provider = None
    return job


class TestLogsStorage:
    """Tests for LogsStorage."""

    def test_get_private_logs_not_allowed_for_user_job(self, mock_cos):
        """get_private_logs raises InvalidAccessException for user jobs (no provider)."""
        with pytest.raises(InvalidAccessException):
            LogsStorage(_mock_job("auth1", provider=None)).get_private_logs()

    def test_save_private_logs_not_allowed_for_user_job(self, mock_cos):
        """save_private_logs raises InvalidAccessException for user jobs."""
        with pytest.raises(InvalidAccessException):
            LogsStorage(_mock_job("auth1", provider=None)).save_private_logs("logs")

    def test_get_public_logs_returns_none_if_not_found(self, mock_cos):
        """get_public_logs returns None when no log exists in COS."""
        logs = LogsStorage(_mock_job("auth1", job_id="nonexistent")).get_public_logs()
        assert logs is None

    def test_get_private_logs_returns_none_if_not_found(self, mock_cos):
        """get_private_logs returns None when no log exists in COS."""
        logs = LogsStorage(_mock_job("auth1", provider="prov1", job_id="nonexistent")).get_private_logs()
        assert logs is None

    def test_save_and_get_public_logs_user_job(self, mock_cos):
        """Test saving and retrieving public logs for a user job."""
        storage = LogsStorage(_mock_job("auth1", provider=None, job_id="job-123"))
        storage.save_public_logs("test log content")
        assert storage.get_public_logs() == "test log content"

    def test_save_and_get_public_logs_provider_job(self, mock_cos):
        """Test saving and retrieving public logs for a provider job."""
        storage = LogsStorage(_mock_job("auth1", provider="prov1", job_id="id"))
        storage.save_public_logs("public log content")
        assert storage.get_public_logs() == "public log content"

    def test_save_and_get_private_logs_provider_job(self, mock_cos):
        """Test saving and retrieving private logs for a provider job."""
        storage = LogsStorage(_mock_job("auth1", provider="prov1", job_id="id"))
        storage.save_private_logs("private log content")
        assert storage.get_private_logs() == "private log content"
