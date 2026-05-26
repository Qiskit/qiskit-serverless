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

"""Tests for FleetsLogsStorage."""

from unittest.mock import MagicMock, patch

import pytest
from ibm_botocore.exceptions import ClientError

from core.models import Program
from core.services.storage import get_logs_storage
from core.services.storage.logs_storage_fleets import FleetsLogsStorage
from tests.utils import TestUtils

_STORAGE_MOD = "core.services.storage.logs_storage_fleets"


@pytest.mark.django_db
class TestFleetsLogsStorage:
    """Unit tests for FleetsLogsStorage."""

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
    def custom_job(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

    @pytest.fixture
    def provider_job(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
        )
        return TestUtils.create_job(author="alice", program=program, code_engine_project=ce_project)

    # ── path generation ────────────────────────────────────────────────────────

    def test_user_log_key_custom_job(self, custom_job):
        """user_log_key uses provider_functions/default path for custom jobs."""
        storage = FleetsLogsStorage(custom_job)
        assert storage._user_log_key == (  # pylint: disable=protected-access
            f"users/alice/provider_functions/default/my-program/jobs/{custom_job.id}/logs.log"
        )

    def test_user_log_key_provider_job(self, provider_job):
        """user_log_key uses provider_functions/<provider> path for provider jobs."""
        storage = FleetsLogsStorage(provider_job)
        assert storage._user_log_key == (  # pylint: disable=protected-access
            f"users/alice/provider_functions/good-partner/my-program/jobs/{provider_job.id}/logs.log"
        )

    def test_provider_log_key_provider_job(self, provider_job):
        """provider_log_key uses providers/<provider> path."""
        storage = FleetsLogsStorage(provider_job)
        assert storage._provider_log_key == (  # pylint: disable=protected-access
            f"providers/good-partner/my-program/jobs/{provider_job.id}/logs.log"
        )

    def test_buckets_come_from_project(self, custom_job):
        """Buckets are taken directly from code_engine_project."""
        storage = FleetsLogsStorage(custom_job)
        assert storage._user_bucket == "user-bucket"  # pylint: disable=protected-access
        assert storage._provider_bucket == "provider-bucket"  # pylint: disable=protected-access

    def test_no_project_raises(self):
        """ValueError raised when job has no CodeEngineProject."""
        program = TestUtils.create_program(program_title="orphan", author="bob", runner=Program.FLEETS)
        job = TestUtils.create_job(author="bob", program=program)
        with pytest.raises(ValueError, match="no CodeEngineProject"):
            FleetsLogsStorage(job)

    # ── get_public_logs ────────────────────────────────────────────────────────

    def test_get_public_logs_returns_content(self, custom_job):
        """get_public_logs decodes and returns COS object content."""
        with patch(f"{_STORAGE_MOD}.get_cos_client") as mock_cos:
            mock_cos.return_value.get_object_bytes.return_value = b"hello logs"
            result = FleetsLogsStorage(custom_job).get_public_logs()
        assert result == "hello logs"

    def test_get_public_logs_returns_none_on_client_error(self, custom_job):
        """get_public_logs returns None when the COS object does not exist yet."""
        with patch(f"{_STORAGE_MOD}.get_cos_client") as mock_cos:
            mock_cos.return_value.get_object_bytes.side_effect = ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
            result = FleetsLogsStorage(custom_job).get_public_logs()
        assert result is None

    def test_get_public_logs_returns_none_when_no_bucket(self, ce_project):
        """get_public_logs returns None when user bucket is not configured."""
        ce_project.cos_bucket_user_data_name = ""
        ce_project.save()
        program = TestUtils.create_program(program_title="no-bucket-prog", author="carol", runner=Program.FLEETS)
        job = TestUtils.create_job(author="carol", program=program, code_engine_project=ce_project)
        result = FleetsLogsStorage(job).get_public_logs()
        assert result is None

    # ── get_private_logs ───────────────────────────────────────────────────────

    def test_get_private_logs_returns_content(self, provider_job):
        """get_private_logs decodes and returns COS object content."""
        with patch(f"{_STORAGE_MOD}.get_cos_client") as mock_cos:
            mock_cos.return_value.get_object_bytes.return_value = b"private logs"
            result = FleetsLogsStorage(provider_job).get_private_logs()
        assert result == "private logs"

    def test_get_private_logs_returns_none_on_client_error(self, provider_job):
        """get_private_logs returns None when the COS object does not exist yet."""
        with patch(f"{_STORAGE_MOD}.get_cos_client") as mock_cos:
            mock_cos.return_value.get_object_bytes.side_effect = ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
            result = FleetsLogsStorage(provider_job).get_private_logs()
        assert result is None

    def test_get_private_logs_returns_none_when_no_bucket(self, ce_project):
        """get_private_logs returns None when provider bucket is not configured."""
        ce_project.cos_bucket_provider_data_name = ""
        ce_project.save()
        program = TestUtils.create_program(
            program_title="no-bucket-prov", author="dave", provider="prov", runner=Program.FLEETS
        )
        job = TestUtils.create_job(author="dave", program=program, code_engine_project=ce_project)
        result = FleetsLogsStorage(job).get_private_logs()
        assert result is None

    # ── save methods not applicable ────────────────────────────────────────────

    def test_save_public_logs_raises(self, custom_job):
        """save_public_logs raises NotImplementedError (container writes COS directly)."""
        with pytest.raises(NotImplementedError):
            FleetsLogsStorage(custom_job).save_public_logs("x")

    def test_save_private_logs_raises(self, provider_job):
        """save_private_logs raises NotImplementedError (container writes COS directly)."""
        with pytest.raises(NotImplementedError):
            FleetsLogsStorage(provider_job).save_private_logs("x")

    # ── factory ────────────────────────────────────────────────────────────────

    def test_factory_returns_fleets_storage_for_fleet_job(self, custom_job):
        """get_logs_storage returns FleetsLogsStorage for FLEETS runner jobs."""
        storage = get_logs_storage(custom_job)
        assert isinstance(storage, FleetsLogsStorage)
