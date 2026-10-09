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
from core.clients.runtime_api_errors import RuntimeApiRetryableError
from core.config_key import ConfigKey
from core.models import (
    CodeEngineProject,
    Config,
    ComputeProfile,
    FunctionSize,
    Job,
    JobConfig,
    JobEvent,
    Program,
)

pytestmark = pytest.mark.django_db


def make_input(**overrides) -> RunFunctionInput:
    defaults = dict(
        title="my-fn",
        provider_name=None,
        arguments="{}",
        config_data=None,
        function_size=None,
        channel=Channel.IBM_QUANTUM_PLATFORM,
        token="tok",
        instance=None,
        account_id=None,
        plan_id=None,
        subscription_id=None,
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
    def test_fleets_job_rejected_when_no_default_size_and_nothing_requested(self, user, ce_project):
        """Nothing requested and no default_size: rejected with clear 400 error."""
        make_fleets_function(user, ce_project)
        ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        with pytest.raises(FunctionConfigurationException):
            RunFunctionUseCase().execute(user, accessible, make_input())

        assert not Job.objects.exists()

    def test_ray_job_leaves_compute_profile_fk_null(self, user):
        """The Ray path has no profile; the FK stays null and no registration is required."""
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        job = RunFunctionUseCase().execute(user, accessible, make_input())

        assert job.compute_profile_id is None
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

        job = RunFunctionUseCase().execute(user, accessible, make_input(function_size="M"))

        assert job.compute_profile_id == "16x128"
        assert job.compute_profile_fk == profile
        # A user-requested size records REQUESTED and the exact size row (so a
        # different size mapping to the same profile stays distinguishable).
        assert job.size_source == Job.SIZE_SOURCE_REQUESTED
        assert job.function_size == size

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

        assert job.compute_profile_id == "16x128"
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

        assert job.compute_profile_id is None
        assert job.compute_profile_fk is None
        assert job.size_source == Job.SIZE_SOURCE_NONE
        assert job.function_size is None


class TestWorkloadMirror:
    CRN = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"

    @pytest.fixture
    def put_function(self):
        with mock.patch("api.use_cases.programs.run.get_functions_operator_client") as get_client:
            yield get_client.return_value.put_function

    @pytest.fixture
    def fleets_accessible(self, user, ce_project, monkeypatch):
        function = make_fleets_function(user, ce_project)
        profile = ComputeProfile.objects.create(compute_profile_id="16x128", cpu="16", memory="128")
        function.default_size = FunctionSize.objects.create(
            function=function, function_size="m", compute_profile=profile
        )
        function.save(update_fields=["default_size"])
        monkeypatch.setattr("api.use_cases.programs.run.get_arguments_storage", lambda job: mock.Mock())
        return FunctionAccessResult(use_legacy_authorization=True, functions=[])

    def test_a_fleets_job_is_sent_to_the_runtime_api_when_it_is_created(self, user, fleets_accessible, put_function):
        Config.set(ConfigKey.WORKLOADS_MIRROR_ENABLED, "true")

        job = RunFunctionUseCase().execute(user, fleets_accessible, make_input(instance=self.CRN))

        put_function.assert_called_once()
        function_id, body = put_function.call_args.args
        assert function_id == str(job.id)
        assert body["status"] == "Queued"

    def test_nothing_is_sent_while_the_mirror_is_off(self, user, fleets_accessible, put_function):
        RunFunctionUseCase().execute(user, fleets_accessible, make_input(instance=self.CRN))

        put_function.assert_not_called()

    def test_a_ray_job_is_not_sent_even_without_instance(self, user, put_function):
        Program.objects.create(title="my-fn", author=user, entrypoint="main.py")
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])
        Config.set(ConfigKey.WORKLOADS_MIRROR_ENABLED, "true")

        RunFunctionUseCase().execute(user, accessible, make_input())

        put_function.assert_not_called()
        assert Job.objects.count() == 1

    def test_the_job_is_not_created_if_the_runtime_api_does_not_take_it(self, user, fleets_accessible, put_function):
        Config.set(ConfigKey.WORKLOADS_MIRROR_ENABLED, "true")
        put_function.side_effect = RuntimeApiRetryableError("down")

        with pytest.raises(RuntimeApiRetryableError):
            RunFunctionUseCase().execute(user, fleets_accessible, make_input(instance=self.CRN))

        assert not Job.objects.exists()
