"""Tests for FleetsLogsStorage."""

from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.exceptions import ClientError

from core.models import Program
from core.services.storage import get_logs_storage
from core.services.storage.logs_storage_fleets import FleetsLogsStorage
from tests.utils import TestUtils

_COS_MODULE = "core.services.storage.logs_storage_fleets.get_cos_client"


def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": ""}}, "GetObject")


@pytest.mark.django_db
class TestFleetsLogsStorage:
    """Tests for FleetsLogsStorage."""

    @pytest.fixture
    def ce_project(self):
        return TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )

    @pytest.fixture
    def job(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

    @pytest.fixture
    def job_with_provider(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

    # ── path generation ────────────────────────────────────────────────────────

    def test_public_key_custom_function(self, job):
        """_public_key uses custom_functions path when program has no provider."""
        storage = FleetsLogsStorage(job)
        assert storage._public_key == (  # pylint: disable=protected-access
            f"users/alice/custom_functions/my-program/jobs/{job.id}/logs.log"
        )

    def test_public_key_provider_function(self, job_with_provider):
        """_public_key uses provider_functions/<provider> path when program has a provider."""
        storage = FleetsLogsStorage(job_with_provider)
        assert storage._public_key == (  # pylint: disable=protected-access
            f"users/alice/provider_functions/good-partner/my-program/jobs/{job_with_provider.id}/logs.log"
        )

    def test_private_key_provider_function(self, job_with_provider):
        """_private_key uses providers/<provider> path."""
        storage = FleetsLogsStorage(job_with_provider)
        assert storage._private_key == (  # pylint: disable=protected-access
            f"providers/good-partner/my-program/jobs/{job_with_provider.id}/logs.log"
        )

    def test_provider_bucket_is_none_for_custom_function(self, job):
        """_provider_bucket is None when program has no provider."""
        storage = FleetsLogsStorage(job)
        assert storage._provider_bucket is None  # pylint: disable=protected-access

    def test_no_project_raises(self):
        """ValueError raised when job has no CodeEngineProject."""
        program = TestUtils.create_program(program_title="orphan", author="bob", runner=Program.FLEETS)
        job = TestUtils.create_job(author="bob", program=program)
        with pytest.raises(ValueError, match="no CodeEngineProject"):
            FleetsLogsStorage(job)

    # ── get_public_logs ────────────────────────────────────────────────────────

    def test_get_public_logs_returns_content(self, job):
        """get_public_logs() returns decoded COS object content."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"public log content"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs()

        assert result == "public log content"
        mock_cos.get_object_bytes.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._public_key,  # pylint: disable=protected-access
        )

    def test_get_public_logs_returns_none_on_not_found(self, job):
        """get_public_logs() returns None when COS object does not exist yet."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs()

        assert result is None

    # ── get_private_logs ───────────────────────────────────────────────────────

    def test_get_private_logs_returns_content(self, job_with_provider):
        """get_private_logs() returns decoded COS object content for provider jobs."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b"private log content"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs()

        assert result == "private log content"
        mock_cos.get_object_bytes.assert_called_once_with(
            bucket_name="provider-bucket",
            key=storage._private_key,  # pylint: disable=protected-access
        )

    def test_get_private_logs_returns_none_on_not_found(self, job_with_provider):
        """get_private_logs() returns None when COS object does not exist yet."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs()

        assert result is None

    def test_get_private_logs_raises_for_custom_function(self, job):
        """get_private_logs() raises RuntimeError for non-provider jobs."""
        storage = FleetsLogsStorage(job)
        with pytest.raises(RuntimeError):
            storage.get_private_logs()

    # ── get_public_logs_url ────────────────────────────────────────────────────

    def test_get_public_logs_url_returns_url_when_object_exists(self, job):
        """get_public_logs_url() returns a presigned URL when the object exists."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_presigned_url.return_value = "https://cos.example.com/logs.log?sig=abc"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs_url()

        assert result == "https://cos.example.com/logs.log?sig=abc"
        mock_cos.head_object.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._public_key,  # pylint: disable=protected-access
        )
        mock_cos.get_presigned_url.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._public_key,  # pylint: disable=protected-access
        )

    def test_get_public_logs_url_returns_none_when_object_not_found(self, job):
        """get_public_logs_url() returns None when the log object does not exist in COS."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_public_logs_url()

        assert result is None
        mock_cos.get_presigned_url.assert_not_called()

    def test_get_public_logs_url_reraises_non_404_cos_error(self, job):
        """get_public_logs_url() re-raises unexpected COS errors (e.g., 403)."""
        storage = FleetsLogsStorage(job)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("AccessDenied")

        with patch(_COS_MODULE, return_value=mock_cos):
            with pytest.raises(ClientError):
                storage.get_public_logs_url()

    # ── get_private_logs_url ───────────────────────────────────────────────────

    def test_get_private_logs_url_returns_url_when_object_exists(self, job_with_provider):
        """get_private_logs_url() returns a presigned URL for provider jobs."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.get_presigned_url.return_value = "https://cos.example.com/private.log?sig=xyz"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs_url()

        assert result == "https://cos.example.com/private.log?sig=xyz"
        mock_cos.head_object.assert_called_once_with(
            bucket_name="provider-bucket",
            key=storage._private_key,  # pylint: disable=protected-access
        )
        mock_cos.get_presigned_url.assert_called_once_with(
            bucket_name="provider-bucket",
            key=storage._private_key,  # pylint: disable=protected-access
        )

    def test_get_private_logs_url_returns_none_when_object_not_found(self, job_with_provider):
        """get_private_logs_url() returns None when the log object does not exist in COS."""
        storage = FleetsLogsStorage(job_with_provider)
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("NotFound")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get_private_logs_url()

        assert result is None

    def test_get_private_logs_url_raises_for_custom_function(self, job):
        """get_private_logs_url() raises RuntimeError for non-provider jobs."""
        storage = FleetsLogsStorage(job)
        with pytest.raises(RuntimeError, match="provider jobs"):
            storage.get_private_logs_url()

    # ── factory ────────────────────────────────────────────────────────────────

    def test_factory_returns_fleets_storage_for_fleet_job(self, job):
        """get_logs_storage returns FleetsLogsStorage for FLEETS runner jobs."""
        storage = get_logs_storage(job)
        assert isinstance(storage, FleetsLogsStorage)
