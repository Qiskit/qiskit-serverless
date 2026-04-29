"""Tests for ResultStorage service."""

from unittest.mock import Mock

from core.services.storage.result_storage import ResultStorage


def _mock_job(username):
    job = Mock()
    job.author = Mock()
    job.author.username = username
    return job


class TestResultStorage:
    """Tests for ResultStorage key generation and COS operations."""

    def test_key_generation(self, mock_cos):
        """Result key is username/results/job_id.json"""
        storage = ResultStorage(_mock_job("user1"))
        assert storage._key("some-id") == "user1/results/some-id.json"

    def test_save_and_get(self, mock_cos):
        """Test saving and retrieving results via COS."""
        storage = ResultStorage(_mock_job("user1"))

        assert storage.get("id") is None

        storage.save("id", "foo")
        assert storage.get("id") == "foo"

        storage.save("id", "overwrite")
        assert storage.get("id") == "overwrite"
