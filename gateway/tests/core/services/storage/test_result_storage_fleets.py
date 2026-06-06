# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

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
    """Create a ClientError with the given error code for testing.

    Args:
        code: The S3 error code (e.g. "NoSuchKey", "404", "AccessDenied").

    Returns:
        A ClientError instance with the specified code.
    """
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
        """Create a fleets job with no provider (custom function)."""
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

    @pytest.fixture
    def job_with_provider(self, ce_project):
        """Create a fleets job with a provider (provider function)."""
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

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
        """_user_bucket comes from the CodeEngineProject."""
        storage = FleetsResultStorage(job)
        assert storage._user_bucket == "user-bucket"  # pylint: disable=protected-access

    def test_no_project_raises_value_error(self):
        """FleetsResultStorage raises ValueError when job has no CodeEngineProject."""
        program = TestUtils.create_program(program_title="orphan", author="bob", runner=Program.FLEETS)
        job = TestUtils.create_job(author="bob", program=program)
        with pytest.raises(ValueError, match="has no CodeEngineProject assigned"):
            FleetsResultStorage(job)

    def test_get_returns_content(self, job):
        """get() returns decoded COS object content."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()
        mock_cos.get_object_bytes.return_value = b'{"result": 42}'

        with patch(_COS_MODULE, return_value=mock_cos) as mock_get_cos:
            result = storage.get()

        assert result == '{"result": 42}'
        mock_get_cos.assert_called_once_with(job.code_engine_project)
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

    def test_save_uploads_to_cos(self, job):
        """save() uploads the result to COS via upload_fileobj."""
        storage = FleetsResultStorage(job)
        mock_cos = MagicMock()

        with patch(_COS_MODULE, return_value=mock_cos):
            storage.save('{"answer": 42}')

        mock_cos.upload_fileobj.assert_called_once()
        call_kwargs = mock_cos.upload_fileobj.call_args[1]
        assert call_kwargs["bucket_name"] == "user-bucket"
        assert call_kwargs["key"] == storage._results_key  # pylint: disable=protected-access

    def test_factory_returns_fleets_storage_for_fleet_job(self, job):
        """get_result_storage returns FleetsResultStorage for FLEETS runner jobs."""
        storage = get_result_storage(job)
        assert isinstance(storage, FleetsResultStorage)
