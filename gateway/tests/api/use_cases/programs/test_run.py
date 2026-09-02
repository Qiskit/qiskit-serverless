"""Unit tests for RunFunctionUseCase."""

from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.authentication.channel import Channel
from api.use_cases.programs.run import RunFunctionUseCase
from api.use_cases.programs.run_input import RunFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import CodeEngineProject, ComputeProfile, FunctionSize, Job, JobConfig, JobEvent, Program

pytestmark = pytest.mark.django_db


def make_input(**overrides) -> RunFunctionInput:
    defaults = dict(
        title="my-fn",
        provider_name=None,
        arguments="{}",
        config_data=None,
        compute_profile=None,
        function_size=None,
        channel=Channel.IBM_QUANTUM_PLATFORM,
        token="tok",
        instance=None,
        account_id=None,
        carrier={},
    )
    return RunFunctionInput(**{**defaults, **overrides})


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def ce_project():
    return CodeEngineProject.objects.create(
        project_id="ce-proj-id",
        project_name="ce-proj",
        region="us-east",
        resource_group_id="rg-id",
        subnet_pool_id="subnet-id",
        pds_name_state="pds-state",
        pds_name_users="pds-users",
        pds_name_providers="pds-providers",
        cos_bucket_user_data_name="user-data-bucket",
    )


def make_fleets_function(user, ce_project):
    return Program.objects.create(
        title="my-fn",
        author=user,
        entrypoint="main.py",
        runner=Program.FLEETS,
        code_engine_project=ce_project,
    )


class TestRunFunctionUseCase:
    def test_creates_job_for_own_function(self, user):
        function = Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.program.title == "my-fn"
        assert job.program.id == function.id
        assert job.author == user

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            RunFunctionUseCase().execute(user, accessible, make_input(title="nonexistent-fn"))

    def test_raises_function_disabled(self, user):
        Program.objects.create(
            title="my-fn",
            author=user,
            entrypoint="main.py",
            disabled=True,
            disabled_message="maintenance",
        )
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionDisabledException):
            RunFunctionUseCase().execute(user, accessible, make_input())

    def test_raises_not_found_when_no_permission_for_custom_function(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            RunFunctionUseCase().execute(user, accessible, make_input())

    @override_settings(LIMITS_ACTIVE_JOBS_PER_USER=1)
    def test_raises_active_job_limit_after_function_resolved(self, user):
        function = Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        Job.objects.create(program=function, author=user, status=Job.QUEUED)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(ActiveJobLimitExceeded):
            RunFunctionUseCase().execute(user, accessible, make_input())

    @override_settings(LIMITS_ACTIVE_JOBS_PER_USER=1)
    def test_raises_not_found_not_limit_when_function_missing(self, user):
        other = User.objects.create_user(username="other")
        other_fn = Program.objects.create(title="other-fn", author=other, entrypoint="main.py")
        Job.objects.create(program=other_fn, author=user, status=Job.QUEUED)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionNotFoundException):
            RunFunctionUseCase().execute(user, accessible, make_input(title="nonexistent-fn"))

    def test_rolls_back_job_and_config_when_creation_fails(self, user, monkeypatch):
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        def boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(JobEvent.objects, "add_status_event", boom)

        with pytest.raises(RuntimeError):
            RunFunctionUseCase().execute(user, accessible, make_input(config_data={"workers": 1}))

        assert not Job.objects.exists()
        assert not JobConfig.objects.exists()

    @override_settings(DEFAULT_COMPUTE_PROFILE="16x128")
    def test_fleets_job_sets_compute_profile_fk_from_default(self, user, ce_project, monkeypatch):
        """A Fleets job resolves its FK from the same bare string it stores in compute_profile."""
        make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        # Arguments storage talks to COS; unrelated to the FK behavior under test.
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.compute_profile == "16x128"
        assert job.compute_profile_fk == profile
        # Nothing requested and no default_size: sized by the deployment default,
        # so no FunctionSize row backs it.
        assert job.size_source == Job.SIZE_SOURCE_SETTINGS_DEFAULT
        assert job.function_size is None

    @override_settings(DEFAULT_COMPUTE_PROFILE="16x128")
    def test_fleets_job_sets_compute_profile_fk_from_explicit_request(self, user, ce_project, monkeypatch):
        """An explicitly requested profile (already bare) is stored and resolves its FK row.

        The use case no longer normalizes: ``RunFunctionInput.compute_profile`` is expected
        to already be in canonical bare form, as it would arrive from the view.
        """
        make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="24x120x1a100p", cpu="24", memory="120")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())

        job = RunFunctionUseCase().execute(user, accessible, make_input(compute_profile="24x120x1a100p"))

        assert job.compute_profile == "24x120x1a100p"
        assert job.compute_profile_fk == profile
        # Sized by the deprecated compute_profile input; no size row applies.
        assert job.size_source == Job.SIZE_SOURCE_COMPUTE_PROFILE
        assert job.function_size is None

    @override_settings(DEFAULT_COMPUTE_PROFILE="16x128")
    def test_fleets_job_does_not_normalize_prefixed_request(self, user, ce_project):
        """A prefixed value is used as-is and fails to resolve a FK.

        Documents that normalization is now the view's responsibility, not the use case's:
        the use case trusts ``RunFunctionInput.compute_profile`` to already be bare.
        """
        make_fleets_function(user, ce_project)
        ComputeProfile.objects.create(compute_profile_id="24x120x1a100p", cpu="24", memory="120")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input(compute_profile="gx3d-24x120x1a100p"))

        assert not Job.objects.exists()

    @override_settings(DEFAULT_COMPUTE_PROFILE="16x128")
    def test_fleets_job_rejected_when_compute_profile_not_registered(self, user, ce_project):
        """An unregistered profile is a misconfiguration: refuse the job, don't persist a null FK."""
        make_fleets_function(user, ce_project)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input())

        assert not Job.objects.exists()

    def test_ray_job_leaves_compute_profile_fk_null(self, user):
        """The Ray path has no profile; the FK stays null and no registration is required."""
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.compute_profile is None
        assert job.compute_profile_fk is None
        assert job.size_source == Job.SIZE_SOURCE_NONE
        assert job.function_size is None

    def test_fleets_job_resolves_compute_profile_from_function_size(self, user, ce_project, monkeypatch):
        """A requested ``function_size`` resolves through the function's catalog to its profile."""
        function = make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        size = FunctionSize.objects.create(function=function, function_size="m", compute_profile=profile)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())

        job = RunFunctionUseCase().execute(user, accessible, make_input(function_size="m"))

        assert job.compute_profile == "16x128"
        assert job.compute_profile_fk == profile
        # A user-requested size records REQUESTED and the exact size row (so a
        # different size mapping to the same profile stays distinguishable).
        assert job.size_source == Job.SIZE_SOURCE_REQUESTED
        assert job.function_size == size

    def test_run_rejects_when_both_compute_profile_and_function_size(self, user, ce_project):
        """Sending both a size and a profile is ambiguous and rejected before any Job is built."""
        function = make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        FunctionSize.objects.create(function=function, function_size="m", compute_profile=profile)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input(function_size="m", compute_profile="16x128"))

        assert not Job.objects.exists()

    def test_run_rejects_unknown_function_size(self, user, ce_project):
        """A size the function does not declare is a 400; no Job is persisted."""
        function = make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        FunctionSize.objects.create(function=function, function_size="m", compute_profile=profile)
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input(function_size="nope"))

        assert not Job.objects.exists()

    def test_fleets_job_uses_default_size_when_nothing_requested(self, user, ce_project, monkeypatch):
        """With neither input, the function's ``default_size`` wins over the settings default."""
        function = make_fleets_function(user, ce_project)
        default_profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        size = FunctionSize.objects.create(function=function, function_size="m", compute_profile=default_profile)
        function.default_size = size
        function.save(update_fields=["default_size"])
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.compute_profile == "16x128"
        assert job.compute_profile_fk == default_profile
        # Platform filled in the default: distinguishable from a user picking the
        # same size, which would record REQUESTED.
        assert job.size_source == Job.SIZE_SOURCE_DEFAULT_SIZE
        assert job.function_size == size

    def test_ray_job_ignores_function_size(self, user):
        """Ray ignores sizing inputs; a stray ``function_size`` leaves the profile and FK null."""
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        job = RunFunctionUseCase().execute(user, accessible, make_input(function_size="m"))

        assert job.compute_profile is None
        assert job.compute_profile_fk is None
        assert job.size_source == Job.SIZE_SOURCE_NONE
        assert job.function_size is None

    def test_ray_job_rejects_when_both_compute_profile_and_function_size(self, user):
        """Ambiguous sizing input is a 400 regardless of runner, even though Ray ignores both anyway.

        The check runs before the Ray short-circuit deliberately: Ray should never receive
        either of these, so a request that sends both is treated as a client mistake worth
        surfacing rather than silently swallowed.
        """
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input(function_size="m", compute_profile="16x128"))

        assert not Job.objects.exists()
