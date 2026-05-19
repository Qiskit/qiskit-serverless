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

from unittest.mock import MagicMock

from core.services.storage.arguments_storage_fleets import FleetsArgumentsStorage


def _make_job(*, provider_name=None):
    job = MagicMock()
    job.id = "job-aaa-111"
    job.author.username = "alice"
    job.program.title = "my-program"
    job.program.provider = MagicMock(name=provider_name) if provider_name else None
    if provider_name:
        job.program.provider.name = provider_name
    job.code_engine_project.project_name = "test-project"
    job.code_engine_project.cos_bucket_user_data_name = "user-bucket"
    return job


def test_arguments_key_custom_function():
    """_arguments_key uses custom_functions path when program has no provider."""
    storage = FleetsArgumentsStorage(_make_job())
    assert storage._arguments_key == (  # pylint: disable=protected-access
        "users/alice/custom_functions/my-program/jobs/job-aaa-111/arguments.json"
    )


def test_arguments_key_provider_function():
    """_arguments_key uses provider_functions path when program has a provider."""
    storage = FleetsArgumentsStorage(_make_job(provider_name="good-partner"))
    assert storage._arguments_key == (  # pylint: disable=protected-access
        "users/alice/provider_functions/good-partner/my-program/jobs/job-aaa-111/arguments.json"
    )
