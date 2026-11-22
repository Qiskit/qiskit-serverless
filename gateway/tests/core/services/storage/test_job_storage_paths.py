"""Tests for the storage paths saved per Fleets job."""

import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.domain.authentication.channel import Channel
from api.use_cases.programs.run import RunFunctionUseCase
from api.use_cases.programs.run_input import RunFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.ibm_cloud.code_engine.fleets import utils as fleet_utils
from core.ibm_cloud.code_engine.fleets.utils import build_fleets_storage_paths, build_job_paths
from core.models import PLATFORM_PERMISSION_RUN, ComputeProfile, FunctionSize, Job, JobStoragePaths, Program
from core.services.storage import get_arguments_storage, get_logs_storage, get_result_storage
from core.services.storage.job_file_explorer import JobFileExplorer
from core.services.storage.job_storage_paths import get_storage_paths, save_storage_paths
from tests.utils import TestUtils, create_function_access_result

# The project of the ce_project fixture, whose HMAC secret signs its COS requests
_PROJECT = ("test-ce-project-id", "us-east")


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
    def job(self, program):
        job = TestUtils.create_job(author="alice", program=program, with_storage_paths=True)
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

    @pytest.fixture(params=["acme", None], ids=["provider_function", "custom_function"])
    def function(self, request, ce_project):
        """A runnable Fleets function, from a provider or the user's own."""
        function = TestUtils.create_program(
            program_title="sampler",
            author="alice",
            provider=request.param,
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )
        if not function.default_size_id:
            profile, _ = ComputeProfile.objects.get_or_create(
                compute_profile_id="16x128", defaults={"cpu": "16", "memory": "128"}
            )
            function.default_size = FunctionSize.objects.create(
                function=function, function_size="m", compute_profile=profile
            )
            function.save(update_fields=["default_size"])
        return function

    def test_a_run_job_keeps_its_files_after_its_function_and_project_are_deleted(self, function, ce_project, fake_cos):
        """Run a job, then delete its function and its Code Engine project: its arguments, results, logs and data
        files are still found where the run put them, with that project's credentials. A provider function uses the
        user and provider buckets, a custom one only the user bucket."""
        job = _run(function, arguments='{"shots": 100}')
        files = _todays_layout(job, function.provider)
        assert fake_cos.read(*_PROJECT, "user-bucket", files.arguments) == '{"shots": 100}'
        _write_as_the_container(fake_cos, files)

        function.delete()
        ce_project.delete()
        job = Job.objects.get(pk=job.pk)

        _assert_the_job_reads_what_its_container_wrote(job, files)
        assert files.arguments in _explore(job)["Job Files"]
        # The data stores are mounted at submit, which a job without its function never reaches: they stay saved
        saved = get_storage_paths(job)
        assert (saved.ce_project_name, saved.user_pds, saved.provider_pds) == (
            "test-project",
            "pds-users",
            "pds-providers" if files.provider_log else None,
        )
        get_arguments_storage(job).delete()
        assert fake_cos.read(*_PROJECT, "user-bucket", files.arguments) is None

    def test_a_job_without_saved_paths_is_read_from_todays_layout_without_saving_them(self, function, fake_cos, caplog):
        """The fallback, for a job created without saved paths: its files are found in today's layout, with one log
        line per read, and no row is saved."""
        job = TestUtils.create_job(author="alice", program=function)
        files = _todays_layout(job, function.provider)
        _write_as_the_container(fake_cos, files)

        with caplog.at_level(logging.INFO, logger="core.JobStoragePaths"):
            assert get_result_storage(job).get() == '{"counts": 1}'

        assert [r.message for r in caplog.records if r.name == "core.JobStoragePaths"] == [
            f"job_id={job.id} has no saved storage paths, reading it from today's layout"
        ]
        _assert_the_job_reads_what_its_container_wrote(job, files)
        assert not JobStoragePaths.objects.filter(job=job).exists()

    def test_a_job_without_a_row_takes_the_project_it_was_created_in(self, program, ce_project):
        """The fallback paths come from the project named on the job, not the function's current one."""
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


def _run(function, arguments: str) -> Job:
    """Run the function as its author, the way the API does."""
    provider = function.provider.name if function.provider else None
    if provider:
        accessible = create_function_access_result(provider, function.title, {PLATFORM_PERMISSION_RUN})
    else:
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
    return RunFunctionUseCase().execute(
        function.author,
        accessible,
        RunFunctionInput(
            title=function.title,
            provider_name=provider,
            arguments=arguments,
            config_data=None,
            function_size=None,
            channel=Channel.IBM_QUANTUM_PLATFORM,
            token="tok",
            instance=None,
            account_id=None,
            plan_id=None,
            subscription_id=None,
            carrier={},
        ),
    )


def _todays_layout(job, provider):
    """Where today's layout puts the files of a job of alice's, written out so the test doesn't trust the code
    under test. A custom function has no provider files."""
    if provider:
        user = f"users/alice/provider_functions/{provider.name}/sampler"
        provider_folder = f"providers/{provider.name}/sampler"
    else:
        user, provider_folder = "users/alice/custom_functions/sampler", None
    return SimpleNamespace(
        arguments=f"{user}/jobs/{job.id}/arguments.json",
        results=f"{user}/jobs/{job.id}/results.json",
        user_log=f"{user}/jobs/{job.id}/logs.log",
        user_data=f"{user}/data/input.txt",
        provider_log=provider_folder and f"{provider_folder}/jobs/{job.id}/logs.log",
        provider_data=provider_folder and f"{provider_folder}/data/model.bin",
    )


def _write_as_the_container(fake_cos, files):
    """What a job leaves in COS when it runs, its results and logs, next to the data files of its function."""
    fake_cos.put(*_PROJECT, "user-bucket", files.results, '{"counts": 1}')
    fake_cos.put(*_PROJECT, "user-bucket", files.user_log, "user log")
    fake_cos.put(*_PROJECT, "user-bucket", files.user_data, "user data")
    if files.provider_log:
        fake_cos.put(*_PROJECT, "provider-bucket", files.provider_log, "provider log")
        fake_cos.put(*_PROJECT, "provider-bucket", files.provider_data, "provider data")


def _explore(job) -> dict[str, set[str]]:
    """The keys the file explorer lists for the job, by category."""
    return {group.category: {f.full_key for f in group.files} for group in JobFileExplorer().explore(job)}


def _assert_the_job_reads_what_its_container_wrote(job, files):
    """Its results and logs, and the file explorer's listing of its job and function folders."""
    assert get_result_storage(job).get() == '{"counts": 1}'
    logs = get_logs_storage(job)
    assert logs.get_public_logs() == "user log"
    listed = _explore(job)
    assert files.user_data in listed["Data Files"]
    assert {files.results, files.user_log} <= listed["Job Files"]
    if files.provider_log:
        assert logs.get_private_logs() == "provider log"
        assert files.provider_data in listed["Provider Data"]
        assert files.provider_log in listed["Provider Job Files"]
    else:
        with pytest.raises(RuntimeError, match="only available for provider jobs"):
            logs.get_private_logs()
        assert not {"Provider Data", "Provider Job Files"} & listed.keys()


_original_provider_paths = fleet_utils.build_provider_job_paths


def _moved_provider_paths(job):
    """A later layout: results.json is renamed and moved out of the job folder."""
    return replace(_original_provider_paths(job), cos_results_key="moved/results.json")
