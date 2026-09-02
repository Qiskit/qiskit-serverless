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
from core.domain.compute_profile import normalize as normalize_compute_profile
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import (
    ComputeProfile,
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


def _get_runner_config(function: Function, compute_profile_requested: str | None) -> RunnerConfig:
    """Resolve (compute_profile string, gpu flag, compute_profile FK) for a run.

    ``compute_profile`` (string) is transitional and will be removed; the FK
    ``compute_profile_fk`` is the source of truth going forward. We derive the FK
    from the same string, so they agree at creation. A Fleets job always resolves
    to a profile string; if no ``ComputeProfile`` row is registered for it, that is
    a deployment misconfiguration and we reject the job rather than store a null FK.
    Ray leaves ``compute_profile`` None (profiles are a Fleets concept), so the FK
    stays null there.

    ``compute_profile_requested`` is expected to already be in the bare
    (prefix-less) canonical form: the view normalizes it before it ever reaches
    this use case. The ``DEFAULT_COMPUTE_PROFILE`` fallback is normalized here,
    because nothing else does it for that path.

    Raises:
        FunctionConfigurationException: If a resolved profile has no registered row.
    """
    if function.runner == Function.FLEETS:
        # The view normalizes what the client asks for, but not this fallback, and a
        # prefixed value here would store a non-canonical profile on the job. The
        # last term keeps an empty setting failing closed: normalize("") is None,
        # and a None profile would skip the "not registered" guard below and persist
        # a job with no profile at all, which then crashes inside the runner.
        compute_profile = (
            compute_profile_requested
            or normalize_compute_profile(settings.DEFAULT_COMPUTE_PROFILE)
            or settings.DEFAULT_COMPUTE_PROFILE
        )
    elif function.provider and function.gpu:
        return RunnerConfig(compute_profile=None, gpu=True, compute_profile_fk=None)
    else:
        return RunnerConfig(compute_profile=None, gpu=False, compute_profile_fk=None)

    compute_profile_fk = ComputeProfile.objects.get_by_id(compute_profile)
    if compute_profile is not None and compute_profile_fk is None:
        raise FunctionConfigurationException(
            f"Compute profile '{compute_profile}' is not registered. Contact administrator."
        )
    return RunnerConfig(compute_profile=compute_profile, gpu=False, compute_profile_fk=compute_profile_fk)


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
            business_model = BusinessModel.TRIAL if trial else BusinessModel.SUBSIDIZED
        else:
            trial = business_model == BusinessModel.TRIAL

        runner_config = _get_runner_config(function, data.compute_profile)
        job = Job(
            trial=trial,
            business_model=business_model,
            status=Job.QUEUED,
            program=function,
            author=user,
            gpu=runner_config.gpu,
            runner=function.runner,
            compute_profile=runner_config.compute_profile,
            compute_profile_fk=runner_config.compute_profile_fk,
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
