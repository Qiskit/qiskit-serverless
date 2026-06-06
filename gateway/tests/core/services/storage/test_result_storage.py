"""Tests for ResultStorage service."""

import os
from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.exceptions import ClientError

from core.models import Program
from core.services.storage.result_storage_fleets import FleetsResultStorage
from core.services.storage.result_storage_ray import RayResultStorage as ResultStorage
from tests.utils import TestUtils

_COS_MODULE = "core.services.storage.result_storage_fleets.get_cos_client"


def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": ""}}, "HeadObject")


@pytest.mark.django_db
class TestResultStorage:
    """Tests for ResultStorage path generation and file operations."""

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

    def test_get_url_raises_not_implemented(self, tmp_path, settings, job):
        """get_url() raises NotImplementedError for Ray jobs."""
        settings.MEDIA_ROOT = str(tmp_path)
        with pytest.raises(NotImplementedError):
            ResultStorage(job=job).get_url()


@pytest.mark.django_db
class TestFleetsResultStorage:
    """Tests for FleetsResultStorage."""

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

    # ── path generation ────────────────────────────────────────────────────────

    def test_results_key_custom_function(self, job):
        """_results_key uses custom_functions path when program has no provider."""
        storage = FleetsResultStorage(job)
        assert storage._results_key == (  # pylint: disable=protected-access
            f"users/alice/custom_functions/my-program/jobs/{job.id}/results.json"
        )

    # ── get ────────────────────────────────────────────────────────────────────

    def test_get_returns_content_when_object_exists(self, job):
        """get() returns decoded content when COS object exists."""
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b'{"answer": 42}'

        with patch(_COS_MODULE, return_value=mock_cos):
            result = FleetsResultStorage(job).get()

        assert result == '{"answer": 42}'

    def test_get_returns_none_when_not_found(self, job):
        """get() returns None when the COS object does not exist."""
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.side_effect = _make_client_error("NoSuchKey")

        with patch(_COS_MODULE, return_value=mock_cos):
            result = FleetsResultStorage(job).get()

        assert result is None

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
