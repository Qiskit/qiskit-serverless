"""Tests for ArgumentsStorage service."""

from unittest.mock import Mock

from core.services.storage.arguments_storage import ArgumentsStorage


def _mock_job(username, function_title, provider_name=None):
    job = Mock()
    job.author = Mock()
    job.author.username = username
    job.program = Mock()
    job.program.title = function_title
    if provider_name:
        job.program.provider = Mock()
        job.program.provider.name = provider_name
    else:
        job.program.provider = None
    return job


class TestArgumentsStorage:
    """Tests for ArgumentsStorage path generation and COS operations."""

    def test_key_without_provider(self, mock_cos):
        """User job: key prefix is username/arguments/"""
        storage = ArgumentsStorage(_mock_job("user1", "myfun"))
        assert storage._sub_path == "user1/arguments"

    def test_key_with_provider(self, mock_cos):
        """Provider job: key prefix is username/provider/function/arguments/"""
        storage = ArgumentsStorage(_mock_job("user1", "myfun", "provider1"))
        assert storage._sub_path == "user1/provider1/myfun/arguments"

    def test_save_and_get(self, mock_cos):
        """Test saving and retrieving arguments via COS."""
        storage = ArgumentsStorage(_mock_job("user1", "myfun"))

        assert storage.get("id") is None

        storage.save("id", "foo")
        assert storage.get("id") == "foo"

        storage.save("id", "overwrite")
        assert storage.get("id") == "overwrite"
