"""Use case: run (enqueue a job for) a Qiskit Function."""

import json
import logging

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.run_input import RunFunctionInput
from api.utils import active_jobs_limit_reached, build_env_variables
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.domain.business_models import BusinessModel
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import (
    Job,
    JobConfig,
    JobEvent,
    Program as Function,
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
)
from core.services.storage import get_arguments_storage
from core.utils import create_gpujob_allowlist, encrypt_env_vars

logger = logging.getLogger("api.api.use_cases.programs.run")


def _is_trial(function: Function, user) -> bool:
    # Single EXISTS query instead of N+1: iterating two unevaluated QuerySets
    # triggers one query per group membership check.
    user_run_groups = Group.objects.filter(user=user, permissions__codename=RUN_PROGRAM_PERMISSION)
    return function.trial_instances.filter(pk__in=user_run_groups).exists()


def _runner_config(function: Function, compute_profile_requested: str | None) -> tuple[str | None, bool]:
    if function.runner == Function.FLEETS:
        profile = compute_profile_requested or getattr(settings, "DEFAULT_COMPUTE_PROFILE", "cx3d-4x16")
        return profile, False
    if function.provider and function.provider.name in create_gpujob_allowlist().get("gpu-functions", {}):
        return None, True
    return None, False


class RunFunctionUseCase:
    """Use case for running (enqueueing a job for) a Qiskit Function."""

    def execute(  # pylint: disable=too-many-locals
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

        if function.runner == Function.FLEETS and not function.code_engine_project:
            raise DRFValidationError("Program has no Code Engine project assigned. Contact administrator.")

        logger.info("user_id=%s program=%s | Creating job", user.id, function.title)

        business_model = None
        if data.provider_name and not accessible_functions.use_legacy_authorization:
            business_model = accessible_functions.get_function(data.provider_name, data.title).business_model

        if business_model is None:
            trial = _is_trial(function, user)
            business_model = BusinessModel.TRIAL if trial else BusinessModel.SUBSIDIZED
        else:
            trial = business_model == BusinessModel.TRIAL

        compute_profile, gpu = _runner_config(function, data.compute_profile)
        jobconfig = JobConfig.objects.create(**data.config_data) if data.config_data else None
        job = Job(
            trial=trial,
            business_model=business_model,
            status=Job.QUEUED,
            program=function,
            author=user,
            config=jobconfig,
            gpu=gpu,
            runner=function.runner,
            compute_profile=compute_profile,
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
        job.save()
        JobEvent.objects.add_status_event(
            job_id=job.id,
            origin=JobEventOrigin.API,
            context=JobEventContext.RUN_PROGRAM,
            status=job.status,
        )
        return job
