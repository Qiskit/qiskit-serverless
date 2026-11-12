"""Tests for the storage paths saved per Fleets job."""

from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from core.ibm_cloud.code_engine.fleets import utils as fleet_utils
from core.ibm_cloud.code_engine.fleets.utils import build_fleets_storage_paths, build_job_paths
from core.models import Job, JobStoragePaths, Program
from core.services.storage import get_arguments_storage, get_logs_storage, get_result_storage
from core.services.storage.job_file_explorer import JobFileExplorer
from core.services.storage.job_storage_paths import get_storage_paths, save_storage_paths
from tests.utils import TestUtils

_COS_FOR = "core.services.storage.job_storage_paths.get_cos_client_for"
_COS_FROM_PROJECT = "core.services.storage.job_storage_paths.get_cos_client"


@pytest.mark.django_db
class TestJobStoragePaths:
    """A Fleets job keeps reading its files from where they were written, with the credentials of the project they
    were written with."""

    @pytest.fixture
    def ce_project(self):
        return TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            region="us-east",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
        )

    @pytest.fixture
    def program(self, ce_project):
        return TestUtils.create_program(
            program_title="sampler",
            author="alice",
            provider="acme",
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )

    @pytest.fixture
    def job(self, program, ce_project):
        job = TestUtils.create_job(author="alice", program=program)
        save_storage_paths(job, build_fleets_storage_paths(job, ce_project))
        return Job.objects.get(pk=job.pk)

    def test_saved_row_holds_the_project_layout_and_names_at_creation(self, job):
        """The row copies the project's id, region, buckets and data stores, and today's keys under their prefix."""
        paths = get_storage_paths(job)

        assert (paths.ce_project_id, paths.ce_project_name, paths.cos_region) == (
            "test-ce-project-id",
            "test-project",
            "us-east",
        )
        assert (paths.user_bucket, paths.provider_bucket) == ("user-bucket", "provider-bucket")
        assert (paths.user_pds, paths.provider_pds) == ("pds-users", "pds-providers")
        assert paths.user_job_prefix == f"users/alice/provider_functions/acme/sampler/jobs/{job.id}"
        assert paths.arguments_key == f"{paths.user_job_prefix}/arguments.json"
        assert paths.provider_log_key == f"providers/acme/sampler/jobs/{job.id}/logs.log"
        assert not paths.problems()

    def test_readers_need_only_the_row_after_the_function_and_project_are_deleted(self, job, program, ce_project):
        """With the function and its project deleted and the layout changed, results, logs, arguments and the file
        explorer still use the saved buckets, keys and project credentials."""
        saved = get_storage_paths(job)
        program.delete()
        ce_project.delete()
        job = Job.objects.get(pk=job.pk)
        assert job.program_id is None
        cos = MagicMock()
        cos.get_object_bytes.return_value = b"content"

        with ExitStack() as stack:
            stack.enter_context(patch.object(fleet_utils, "build_provider_job_paths", _moved_provider_paths))
            cos_for = stack.enter_context(patch(_COS_FOR, return_value=cos))
            from_project = stack.enter_context(patch(_COS_FROM_PROJECT))
            get_result_storage(job).get()
            get_logs_storage(job).get_public_logs()
            get_logs_storage(job).get_private_logs()
            get_arguments_storage(job).delete()
            JobFileExplorer().explore(job)

        assert {c.args for c in cos_for.call_args_list} == {("test-ce-project-id", "us-east")}
        from_project.assert_not_called()
        read = {(c.kwargs["bucket_name"], c.kwargs["key"]) for c in cos.get_object_bytes.call_args_list}
        assert read == {
            ("user-bucket", saved.results_key),
            ("user-bucket", saved.user_log_key),
            ("provider-bucket", saved.provider_log_key),
        }
        assert cos.delete_object.call_args.kwargs["key"] == saved.arguments_key
        assert {c.kwargs["bucket_name"] for c in cos.list_with_metadata.call_args_list} == {
            "user-bucket",
            "provider-bucket",
        }

    def test_a_job_without_a_row_saves_one_on_its_first_read_and_keeps_it(self, program, ce_project):
        """A job from an old pod has no row: the first read saves today's paths, and a later layout change or
        bucket rename doesn't move it."""
        job = TestUtils.create_job(author="alice", program=program)
        job = Job.objects.get(pk=job.pk)

        first = get_storage_paths(job)
        ce_project.cos_bucket_user_data_name = "renamed-user-bucket"
        ce_project.save()
        with patch.object(fleet_utils, "build_provider_job_paths", _moved_provider_paths):
            later = get_storage_paths(Job.objects.get(pk=job.pk))

        assert JobStoragePaths.objects.filter(job=job).count() == 1
        assert later == first
        assert (later.user_bucket, later.ce_project_id) == ("user-bucket", "test-ce-project-id")

    def test_a_job_without_a_row_takes_the_project_it_was_created_in(self, program, ce_project):
        """The paths saved on first read come from the project named on the job, not the function's current one."""
        job = TestUtils.create_job(author="alice", program=program)
        Job.objects.filter(pk=job.pk).update(ce_project_name=ce_project.project_name, ce_region=ce_project.region)
        program.code_engine_project = TestUtils.get_or_create_ce_project(
            project_name="new-project", project_id="new-id", cos_bucket_user_data_name="new-bucket"
        )
        program.save()

        paths = get_storage_paths(Job.objects.get(pk=job.pk))

        assert (paths.ce_project_id, paths.user_bucket) == ("test-ce-project-id", "user-bucket")

    def test_a_job_without_a_row_and_without_a_function_cant_be_read(self, program):
        """With no row and no function there is nothing to build the paths from, so readers get a clear error."""
        job = TestUtils.create_job(author="alice", program=program)
        program.delete()

        with pytest.raises(ValueError, match="function was deleted"):
            get_storage_paths(Job.objects.get(pk=job.pk))
        assert not JobStoragePaths.objects.filter(job=job).exists()

    def test_a_row_without_a_project_id_falls_back_to_the_functions_project(self, job, ce_project):
        """A row saved when its project could not be found reads COS with the function's current project."""
        JobStoragePaths.objects.filter(job=job).update(ce_project_id=None, ce_project_name=None)
        job = Job.objects.get(pk=job.pk)
        cos = MagicMock()
        cos.get_object_bytes.return_value = b"content"

        with patch(_COS_FROM_PROJECT, return_value=cos) as from_project, patch(_COS_FOR) as cos_for:
            get_result_storage(job).get()

        from_project.assert_called_once_with(ce_project)
        cos_for.assert_not_called()

    def test_a_provider_job_needs_the_provider_bucket_and_data_store(self, program, ce_project):
        """A provider job is never saved without a provider bucket, so its submit can't fail later on a None."""
        job = TestUtils.create_job(author="alice", program=program)
        ce_project.cos_bucket_provider_data_name = None

        with pytest.raises(ValueError, match="no cos_bucket_provider_data_name"):
            build_fleets_storage_paths(job, ce_project)

    def test_the_container_gets_the_saved_keys_after_a_file_rename_in_the_code(self, job):
        """A file renamed in the code while the job is queued: the container still writes to the saved key."""
        saved = get_storage_paths(job)

        with patch.object(fleet_utils, "build_provider_job_paths", _moved_provider_paths):
            paths = build_job_paths(job, saved)

        assert paths.cos_results_key == saved.results_key
        assert paths.container_result_path == "/job_user_data/results.json"
        assert paths.container_arguments_path == "/job_user_data/arguments.json"
        assert paths.container_public_log_path == "/job_user_data/logs.log"
        assert paths.container_private_log_path == "/job_provider_data/logs.log"
        assert paths.cos_user_job_prefix == saved.user_job_prefix

    def test_a_key_outside_its_job_prefix_is_refused(self, job):
        """A key the container can't reach through its mounts is never saved."""
        paths = replace(get_storage_paths(job), results_key="somewhere/else/results.json")
        JobStoragePaths.objects.filter(job=job).delete()

        with pytest.raises(ValueError, match="results_key is not under user_job_prefix"):
            save_storage_paths(job, paths)
        assert not JobStoragePaths.objects.filter(job=job).exists()


_original_provider_paths = fleet_utils.build_provider_job_paths


def _moved_provider_paths(job):
    """A later layout: results.json is renamed and moved out of the job folder."""
    return replace(_original_provider_paths(job), cos_results_key="moved/results.json")
