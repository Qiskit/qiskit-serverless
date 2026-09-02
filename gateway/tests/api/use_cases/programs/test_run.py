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
from api.use_cases.programs.run import RunFunctionUseCase, _get_runner_config
from api.use_cases.programs.run_input import RunFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import CodeEngineProject, ComputeProfile, Job, JobConfig, JobEvent, Program
from tests.utils import TestUtils

pytestmark = pytest.mark.django_db


def make_input(**overrides) -> RunFunctionInput:
    defaults = dict(
        title="my-fn",
        provider_name=None,
        arguments="{}",
        config_data=None,
        compute_profile=None,
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

    @override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
    def test_fleets_job_sets_compute_profile_fk_from_default(self, user, ce_project, monkeypatch):
        """A Fleets job resolves its FK from the same bare string it stores in compute_profile."""
        make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="24x120", cpu="24", memory="120")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        # Arguments storage talks to COS; unrelated to the FK behavior under test.
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.compute_profile == "24x120"
        assert job.compute_profile_fk == profile

    @override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
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

    @override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
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

    @override_settings(DEFAULT_COMPUTE_PROFILE="24x120")
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


def test_the_default_compute_profile_is_normalized(settings):
    """A prefixed DEFAULT_COMPUTE_PROFILE still stores the canonical form on the job."""
    settings.DEFAULT_COMPUTE_PROFILE = "bx3d-24x120"
    ComputeProfile.objects.get_or_create(compute_profile_id="24x120", defaults={"cpu": "24", "memory": "120"})
    function = TestUtils.create_program(
        program_title="normalize-default-function", author="normalize_user", runner=Program.FLEETS
    )

    config = _get_runner_config(function, None)

    assert config.compute_profile == "24x120"
