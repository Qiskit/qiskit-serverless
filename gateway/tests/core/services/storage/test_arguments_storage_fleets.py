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

"""Tests for FleetsArgumentsStorage."""

import pytest

from core.models import Program
from core.services.storage.arguments_storage_fleets import FleetsArgumentsStorage
from tests.utils import TestUtils


@pytest.mark.django_db
class TestFleetsArgumentsStorage:
    """Tests for FleetsArgumentsStorage path generation."""

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
            code_engine_project=ce_project,
        )
        return TestUtils.create_job(author="alice", program=program)

    @pytest.fixture
    def job_with_provider(self, ce_project):
        program = TestUtils.create_program(
            program_title="my-program",
            author="alice",
            provider="good-partner",
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )
        return TestUtils.create_job(author="alice", program=program)

    def test_arguments_key_custom_function(self, job):
        """_arguments_key uses custom_functions path when program has no provider."""
        storage = FleetsArgumentsStorage(job)
        assert storage._arguments_key == (  # pylint: disable=protected-access
            f"users/alice/custom_functions/my-program/jobs/{job.id}/arguments.json"
        )

    def test_arguments_key_provider_function(self, job_with_provider):
        """_arguments_key uses provider_functions path when program has a provider."""
        storage = FleetsArgumentsStorage(job_with_provider)
        assert storage._arguments_key == (  # pylint: disable=protected-access
            f"users/alice/provider_functions/good-partner/my-program/jobs/{job_with_provider.id}/arguments.json"
        )
