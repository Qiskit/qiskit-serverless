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

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from core.services.storage.job_file_explorer import FileEntry, FileGroup, JobFileExplorer


def _make_job(runner="fleets", has_provider=False):
    job = MagicMock()
    job.id = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    job.author.username = "alice"
    job.runner = runner
    job.program.title = "my-fn"
    job.program.runner = runner
    if has_provider:
        job.program.provider = MagicMock()
        job.program.provider.name = "acme"
    else:
        job.program.provider = None
    job.program.code_engine_project = MagicMock()
    job.program.code_engine_project.cos_bucket_user_data_name = "user-bucket"
    job.program.code_engine_project.cos_bucket_provider_data_name = "provider-bucket"
    return job


TS = datetime(2024, 5, 10, 14, 32, 0, tzinfo=timezone.utc)


def _cos_objects(*names, bucket_prefix=""):
    return [{"key": f"{bucket_prefix}{n}", "size": 100, "last_modified": TS} for n in names]


class TestJobFileExplorerFleets(TestCase):
    @patch("core.services.storage.job_file_explorer.get_cos_client")
    def test_custom_function_data_files_grouped(self, mock_get_cos):
        job = _make_job(runner="fleets", has_provider=False)
        cos = MagicMock()
        mock_get_cos.return_value = cos
        prefix = "users/alice/custom_functions/my-fn/data"
        cos.list_with_metadata.side_effect = lambda *, bucket_name, prefix: (
            _cos_objects("file.py", bucket_prefix=prefix + "/")
            if prefix == "users/alice/custom_functions/my-fn/data"
            else []
        )

        groups = JobFileExplorer().explore(job)

        data_group = next((g for g in groups if g.category == "Data Files"), None)
        assert data_group is not None
        assert len(data_group.files) == 1
        assert data_group.files[0].name == "file.py"
        assert data_group.files[0].size_bytes == 100
        assert data_group.files[0].last_modified == TS
        assert data_group.files[0].bucket_or_path == "user-bucket"

    @patch("core.services.storage.job_file_explorer.get_cos_client")
    def test_job_artifacts_split_into_groups(self, mock_get_cos):
        job = _make_job(runner="fleets", has_provider=False)
        cos = MagicMock()
        mock_get_cos.return_value = cos
        job_prefix = f"users/alice/custom_functions/my-fn/jobs/{job.id}/"
        artifact_objects = [
            {"key": f"{job_prefix}results.json", "size": 500, "last_modified": TS},
            {"key": f"{job_prefix}logs.log", "size": 1200, "last_modified": TS},
            {"key": f"{job_prefix}arguments.json", "size": 80, "last_modified": TS},
        ]
        cos.list_with_metadata.side_effect = lambda *, bucket_name, prefix: (
            artifact_objects if prefix == job_prefix else []
        )

        groups = JobFileExplorer().explore(job)

        categories = {g.category for g in groups}
        assert "Results" in categories
        assert "Logs" in categories
        assert "Arguments" in categories

    @patch("core.services.storage.job_file_explorer.get_cos_client")
    def test_empty_groups_are_omitted(self, mock_get_cos):
        job = _make_job(runner="fleets", has_provider=False)
        cos = MagicMock()
        mock_get_cos.return_value = cos
        cos.list_with_metadata.return_value = []

        groups = JobFileExplorer().explore(job)

        assert groups == []

    @patch("core.services.storage.job_file_explorer.get_cos_client")
    def test_cos_error_on_one_prefix_skips_that_group(self, mock_get_cos):
        job = _make_job(runner="fleets", has_provider=False)
        cos = MagicMock()
        mock_get_cos.return_value = cos
        job_prefix = f"users/alice/custom_functions/my-fn/jobs/{job.id}/"

        def side_effect(*, bucket_name, prefix):
            if prefix == job_prefix:
                raise Exception("COS unavailable")
            return _cos_objects("file.py", bucket_prefix=prefix + "/")

        cos.list_with_metadata.side_effect = side_effect

        groups = JobFileExplorer().explore(job)

        categories = {g.category for g in groups}
        assert "Data Files" in categories
        assert "Results" not in categories
        assert "Logs" not in categories
