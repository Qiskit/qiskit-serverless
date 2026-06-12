"""Tests for FleetsResultStorage."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.exceptions import ClientError

from core.models import Program
from core.services.storage import get_result_storage
from core.services.storage.result_storage_fleets import FleetsResultStorage
from tests.utils import TestUtils

_COS_MODULE = "core.services.storage.result_storage_fleets.get_cos_client"


def _make_client_error(code: str) -> ClientError:
    """Create a ClientError with the given error code for testing."""
    return ClientError({"Error": {"Code": code, "Message": ""}}, "GetObject")


@pytest.mark.django_db
class TestFleetsResultStorage:
    """Tests for FleetsResultStorage."""

    @pytest.fixture
    def ce_project(self):
        """Create a CodeEngineProject with test bucket names."""
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
        """Create a fleets job with CE project on the program."""
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )
        return TestUtils.create_job(author="alice", program=program)

    @pytest.fixture
    def job_with_provider(self, ce_project):
        """Create a fleets job with a provider."""
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )
        return TestUtils.create_job(author="alice", program=program)

    def test_results_key_custom_function(self, job):
        """_results_key uses custom_functions path when program has no provider."""
        storage = FleetsResultStorage(job)
        assert storage._results_key == (  # pylint: disable=protected-access
            f"users/alice/custom_functions/my-program/jobs/{job.id}/results.json"
        )

    def test_results_key_provider_function(self, job_with_provider):
        """_results_key uses provider_functions path when program has a provider."""
        storage = FleetsResultStorage(job_with_provider)
        assert storage._results_key == (  # pylint: disable=protected-access
            f"users/alice/provider_functions/good-partner/my-program/jobs/{job_with_provider.id}/results.json"
        )

    def test_user_bucket_from_project(self, job):
        """_user_bucket comes from the program's CodeEngineProject."""
        storage = FleetsResultStorage(job)
        assert storage._user_bucket == "user-bucket"  # pylint: disable=protected-access

    def test_get_returns_content(self, job):
        """get() returns decoded COS object content."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b'{"result": 42}'

        with patch(_COS_MODULE, return_value=mock_cos) as mock_get_cos:
            result = storage.get()

        assert result == '{"result": 42}'
        mock_get_cos.assert_called_once_with(job.program.code_engine_project)
        mock_cos.get_object_bytes.assert_called_once_with(
            bucket_name="user-bucket",
            key=storage._results_key,  # pylint: disable=protected-access
        )

    def test_get_returns_none_on_not_found(self, job):
        """get() returns None when COS object does not exist yet."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get()

        assert result is None

    def test_get_returns_none_on_404(self, job):
        """get() returns None when COS returns a 404 error code."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("404")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = storage.get()

        assert result is None

    def test_get_returns_none_on_other_client_error(self, job, caplog):
        """get() returns None and logs error on unexpected ClientError."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("AccessDenied")

        with caplog.at_level(logging.ERROR, logger="core.FleetsResultStorage"):
            with patch(_COS_MODULE, return_value=mock_cos):
                result = storage.get()

        assert result is None
        assert any("COS error AccessDenied" in record.message for record in caplog.records)

    def test_save_raises_not_implemented(self, job):
        """save() raises NotImplementedError — results are written by the SDK."""
        storage = FleetsResultStorage(job)
        with pytest.raises(NotImplementedError):
            storage.save("some result")

    # ── get_url ────────────────────────────────────────────────────────────────

    def test_get_url_returns_url_when_object_exists(self, job):
        """get_url() returns a presigned URL when the COS object exists."""
        mock_cos = MagicMock()
        mock_cos.get_presigned_url.return_value = "https://cos.example.com/results.json?sig=abc"

        with patch(_COS_MODULE, return_value=mock_cos):
            result = FleetsResultStorage(job).get_url()

        assert result == "https://cos.example.com/results.json?sig=abc"
        mock_cos.head_object.assert_called_once()
        mock_cos.get_presigned_url.assert_called_once()

    def test_get_url_returns_none_when_not_found(self, job):
        """get_url() returns None when the COS object does not exist."""
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = FleetsResultStorage(job).get_url()

        assert result is None
        mock_cos.get_presigned_url.assert_not_called()

    def test_get_url_returns_none_on_404(self, job):
        """get_url() returns None for 404 COS error."""
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("404")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = FleetsResultStorage(job).get_url()

        assert result is None

    def test_get_url_reraises_non_404_cos_error(self, job):
        """get_url() re-raises unexpected COS errors (e.g., 403)."""
        mock_cos = MagicMock()
        mock_cos.head_object.side_effect = _make_client_error("AccessDenied")

        with patch(_COS_MODULE, return_value=mock_cos):
            with pytest.raises(ClientError):
                FleetsResultStorage(job).get_url()

    def test_factory_returns_fleets_storage_for_fleet_job(self, job):
        """get_result_storage returns FleetsResultStorage for FLEETS runner jobs."""
        storage = get_result_storage(job)
        assert isinstance(storage, FleetsResultStorage)
