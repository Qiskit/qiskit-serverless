"""Use case: run (enqueue a job for) a Qiskit Function."""

import json
import logging

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.db import transaction

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.run_input import RunFunctionInput
from api.use_cases.programs.runner_config import RunnerConfig
from api.use_cases.programs.validate_arguments import validate_arguments
from api.utils import active_jobs_limit_reached, build_env_variables
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import (
    ComputeProfile,
    FunctionSize,
    Job,
    JobConfig,
    JobEvent,
    Program as Function,
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
)
from core.services.storage import get_arguments_storage
from core.utils import encrypt_env_vars

logger = logging.getLogger("api.api.use_cases.programs.run")


def _is_trial(function: Function, user) -> bool:
    # Single EXISTS query instead of N+1: iterating two unevaluated QuerySets
    # triggers one query per group membership check.
    user_run_groups = Group.objects.filter(user=user, permissions__codename=RUN_PROGRAM_PERMISSION)
    return function.trial_instances.filter(pk__in=user_run_groups).exists()


def _config_for_profile_id(compute_profile: str, *, size_source: str) -> RunnerConfig:
    """Build a Fleets RunnerConfig from a bare compute profile id.

    The id must name a registered ``ComputeProfile`` row; a missing row is a
    deployment misconfiguration and we reject the job rather than store a null FK.
    No ``FunctionSize`` row backs a profile resolved this way (the deprecated
    ``compute_profile`` input or the deployment default), so ``function_size``
    is null; ``size_source`` records which of those it was.
    """
    compute_profile_fk = ComputeProfile.objects.get_by_id(compute_profile)
    if compute_profile_fk is None:
        raise FunctionConfigurationException(
            f"Compute profile '{compute_profile}' is not registered. Contact administrator."
        )
    return RunnerConfig(
        compute_profile=compute_profile,
        gpu=False,
        compute_profile_fk=compute_profile_fk,
        size_source=size_source,
        function_size=None,
    )


def _get_runner_config(
    function: Function,
    compute_profile_requested: str | None,
    function_size_requested: str | None,
) -> RunnerConfig:
    """Resolve the compute profile and sizing provenance for a run.

    ``compute_profile_fk`` is the source of truth for the profile a job runs at
    and is what gets stored on the job. A Fleets job always resolves to a profile;
    if no ``ComputeProfile`` row is registered for it, that is a deployment
    misconfiguration and we reject the job rather than store a null FK. Ray is not
    profiled (profiles are a Fleets concept), so its FK stays null.

    Because the size determines the compute profile (and not the reverse -- two
    sizes can map to one profile), the returned :class:`RunnerConfig` also records
    ``size_source`` (how sizing was chosen) and, where one applies, the
    ``FunctionSize`` row itself, so a stored job stays distinguishable.

    Sizing precedence (Fleets):
        1. Both ``function_size`` and ``compute_profile`` -> rejected as ambiguous.
        2. ``function_size`` -> resolved through the function's ``FunctionSize``
           catalog (source REQUESTED); an undeclared size is rejected.
        3. ``compute_profile`` (deprecated) -> used as-is (source COMPUTE_PROFILE).
        4. Neither -> the function's ``default_size`` (source DEFAULT_SIZE), else
           ``settings.DEFAULT_COMPUTE_PROFILE`` (source SETTINGS_DEFAULT).

    Both requested values are expected already normalized by the view:
    ``compute_profile`` to bare (prefix-less) form, ``function_size`` to its
    canonical (strip+casefold) label.

    Raises:
        FunctionConfigurationException: on ambiguous input, an undeclared size, or
            a resolved profile with no registered row.
    """
    # Ambiguous input is always a 400, whatever the runner, so check before the
    # Ray short-circuit.
    if compute_profile_requested and function_size_requested:
        raise FunctionConfigurationException(
            "Provide either 'function_size' or 'compute_profile', not both. "
            "'compute_profile' is deprecated; prefer 'function_size'."
        )

    if function.runner != Function.FLEETS:
        # Ray / GPU: sizes and profiles do not apply; both requested values are ignored.
        gpu = bool(function.provider and function.gpu)
        return RunnerConfig(
            compute_profile=None,
            gpu=gpu,
            compute_profile_fk=None,
            size_source=Job.SIZE_SOURCE_NONE,
            function_size=None,
        )

    # (2) An explicitly requested size resolves through the function's catalog.
    # Fetch the FunctionSize row itself so we can record it (billing keys off the
    # size tier); the compute profile comes from that same row.
    if function_size_requested:
        function_size = FunctionSize.objects.get_function_size(function, function_size_requested)
        if function_size is None:
            available = sorted(FunctionSize.objects.function_sizes(function).values_list("function_size", flat=True))
            available_msg = ", ".join(available) if available else "this function declares no sizes."
            raise FunctionConfigurationException(
                f"Unknown function size '{function_size_requested}' for this function. "
                f"Available sizes: {available_msg}"
            )
        profile = function_size.compute_profile
        return RunnerConfig(
            compute_profile=profile.compute_profile_id,
            gpu=False,
            compute_profile_fk=profile,
            size_source=Job.SIZE_SOURCE_REQUESTED,
            function_size=function_size,
        )

    # (3) Deprecated explicit compute profile.
    if compute_profile_requested:
        logger.warning(
            "program=%s | 'compute_profile' is deprecated; use 'function_size'.",
            function.title,
        )
        return _config_for_profile_id(compute_profile_requested, size_source=Job.SIZE_SOURCE_COMPUTE_PROFILE)

    # (4a) Nothing requested: the function's default size.
    if function.default_size_id:
        function_size = function.default_size
        profile = function_size.compute_profile
        return RunnerConfig(
            compute_profile=profile.compute_profile_id,
            gpu=False,
            compute_profile_fk=profile,
            size_source=Job.SIZE_SOURCE_DEFAULT_SIZE,
            function_size=function_size,
        )

    # (4b) No default size either: the deployment-wide default profile.
    return _config_for_profile_id(settings.DEFAULT_COMPUTE_PROFILE, size_source=Job.SIZE_SOURCE_SETTINGS_DEFAULT)


class RunFunctionUseCase:
    """Use case for running (enqueueing a job for) a Qiskit Function."""

    def execute(  # pylint: disable=too-many-locals, too-many-branches
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        data: RunFunctionInput,
    ) -> Job:
        """Enqueue a job for the specified Qiskit Function.

        Raises FunctionNotFoundException or FunctionDisabledException as appropriate.
        """
        function = None
        if data.provider_name:
            function = Function.objects.get_function_by_permission(
                user=user,
                function_title=data.title,
                provider_name=data.provider_name,
                accessible_functions=accessible_functions,
                permission=PLATFORM_PERMISSION_RUN,
                legacy_permission_name=RUN_PROGRAM_PERMISSION,
            )
        else:
            if JobAccessPolicies.can_create(user=user, accessible_functions=accessible_functions):
                function = Function.objects.get_user_function(user, data.title)

        if function is None:
            raise FunctionNotFoundException(function=data.title, provider=data.provider_name)

        if function.disabled:
            message = function.disabled_message if function.disabled_message else Function.DEFAULT_DISABLED_MESSAGE
            raise FunctionDisabledException(message=message)

        if active_jobs_limit_reached(user):
            raise ActiveJobLimitExceeded()

        if function.runner == Function.FLEETS:
            message = None
            if not function.code_engine_project:
                message = "Program has no Code Engine project assigned. Contact administrator."
            elif not function.code_engine_project.active:
                message = (
                    f"Code Engine project '{function.code_engine_project.project_name}' assigned to "
                    "this function is not active. Contact administrator."
                )
            if message:
                logger.warning("user_id=%s program=%s | %s", user.id, function.title, message)
                raise FunctionConfigurationException(message)

        validate_arguments(function, data.arguments)

        logger.info("user_id=%s program=%s | Creating job", user.id, function.title)

        business_model = None
        if data.provider_name and not accessible_functions.use_legacy_authorization:
            business_model = accessible_functions.get_function(data.provider_name, data.title).business_model

        if business_model is None:
            trial = _is_trial(function, user)
            business_model = BusinessModel.TRIAL if trial else BusinessModel.LICENSED
        else:
            trial = business_model == BusinessModel.TRIAL

        runner_config = _get_runner_config(function, data.compute_profile, data.function_size)
        job = Job(
            trial=trial,
            business_model=business_model,
            status=Job.QUEUED,
            program=function,
            author=user,
            gpu=runner_config.gpu,
            runner=function.runner,
            compute_profile_fk=runner_config.compute_profile_fk,
            size_source=runner_config.size_source,
            function_size=runner_config.function_size,
            instance_crn=data.instance,
            account_id=data.account_id,
            ce_project_name=function.code_engine_project.project_name if function.code_engine_project else None,
            ce_region=function.code_engine_project.region if function.code_engine_project else None,
        )

        env = encrypt_env_vars(
            build_env_variables(
                channel=data.channel,
                token=data.token,
                job=job,
                trial_mode=trial,
                instance=data.instance,
            )
        )
        try:
            env["traceparent"] = data.carrier["traceparent"]
        except KeyError:
            pass
        if function.env_vars:
            env.update(json.loads(function.env_vars))
        job.env_vars = json.dumps(env)

        get_arguments_storage(job).save(data.arguments)

        with transaction.atomic():
            if data.config_data:
                job.config = JobConfig.objects.create(**data.config_data)
            job.save()
            JobEvent.objects.add_status_event(
                job_id=job.id,
                origin=JobEventOrigin.API,
                context=JobEventContext.RUN_PROGRAM,
                status=job.status,
            )
        return job
