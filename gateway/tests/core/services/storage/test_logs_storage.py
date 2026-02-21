"""Tests for LogsStorage."""

import tempfile
import os

from django.test import TestCase
from unittest.mock import Mock

from api.domain.exceptions.forbidden_error import ForbiddenError
from core.services.storage.logs_storage import LogsStorage


class TestLogsStorage(TestCase):
    """Tests for LogsStorage."""

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

        with self.assertRaises(ForbiddenError):
            LogsStorage(job).get_private_logs()

    def test_save_private_logs_not_allowed_for_user_job(self):
        """save_private_logs is not allowed for user jobs."""
        job = self._create_job("auth1", provider=None)

        with self.assertRaises(ForbiddenError):
            LogsStorage(job).save_private_logs("some logs")

    def test_get_public_logs_returns_none_if_not_found(self):
        """get_public_logs returns None if file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir):
                job = self._create_job("auth1", job_id="nonexistent")
                storage = LogsStorage(job)
                logs = storage.get_public_logs()

                self.assertIsNone(logs)

    def test_get_private_logs_returns_none_if_not_found(self):
        """get_public_logs returns None if file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.settings(MEDIA_ROOT=temp_dir):
                job = self._create_job("auth1", provider="prov1", job_id="nonexistent")
                storage = LogsStorage(job)
                logs = storage.get_private_logs()

                self.assertIsNone(logs)

    def test_save_and_get_public_logs_user_job(self):
        """Test saving and retrieving public logs for a user job."""
        job = self._create_job("auth1", provider=None, job_id="job-123")
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_path = os.path.join(temp_dir, "auth1", "logs", "job-123.log")
            with self.settings(MEDIA_ROOT=temp_dir):
                storage = LogsStorage(job)
                storage.save_public_logs("test log content")
                logs = storage.get_public_logs()

                self.assertEqual(logs, "test log content")
                self.assertTrue(os.path.exists(expected_path))

    def test_save_and_get_public_logs_provider_job(self):
        """Test saving and retrieving public logs for a provider job."""
        job = self._create_job("auth1", provider="prov1", job_id="id")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "auth1", "prov1", "func1", "logs", "id.log")
            with self.settings(MEDIA_ROOT=temp_dir):
                storage = LogsStorage(job)
                storage.save_public_logs("public log content")
                logs = storage.get_public_logs()

                self.assertEqual(logs, "public log content")
                self.assertTrue(os.path.exists(path))

    def test_save_and_get_private_logs_provider_job(self):
        """Test saving and retrieving private logs for a provider job."""
        job = self._create_job("auth1", provider="prov1", job_id="id")
        with tempfile.TemporaryDirectory() as temp_dir:
            expected_path = os.path.join(temp_dir, "prov1", "func1", "logs", "id.log")
            with self.settings(MEDIA_ROOT=temp_dir):
                storage = LogsStorage(job)
                storage.save_private_logs("private log content")
                logs = storage.get_private_logs()

                self.assertEqual(logs, "private log content")
                self.assertTrue(os.path.exists(expected_path))
