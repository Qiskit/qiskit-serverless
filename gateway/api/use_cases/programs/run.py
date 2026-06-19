"""Use case: run (enqueue a job for) a Qiskit Function."""

import re

from django.contrib.auth.models import AbstractUser
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.run_input import RunFunctionInput
from api.utils import active_jobs_limit_reached
from api.v1.serializers import JobConfigSerializer, RunJobSerializer
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    Job,
    Program as Function,
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
)


class RunFunctionUseCase:
    """Use case for running (enqueueing a job for) a Qiskit Function."""

    def execute(  # pylint: disable=too-many-locals
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        data: RunFunctionInput,
    ) -> Job:
        """Enqueue a job for the specified Qiskit Function.

        Raises FunctionNotFoundException, FunctionDisabledException, or ActiveJobLimitExceeded
        as appropriate.
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

        jobconfig = None
        if data.config_json:
            job_config_serializer = JobConfigSerializer(data=data.config_json)
            job_config_serializer.is_valid(raise_exception=True)
            jobconfig = job_config_serializer.save()

        if data.compute_profile:
            if not re.match(r"^[a-z]+\d+[a-z]?-\d+x\d+(?:x\d+[a-z0-9]+)?$", data.compute_profile):
                error_msg = (
                    f"Invalid compute profile format: '{data.compute_profile}'. "
                    f"Expected format: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type] "
                    f"(lowercase only, e.g., 'cx3d-4x16' or 'gx3d-24x120x1a100p')"
                )
                raise DRFValidationError({"compute_profile": [error_msg]})

        if active_jobs_limit_reached(user):
            raise ActiveJobLimitExceeded()

        business_model = None
        if data.provider_name and not accessible_functions.use_legacy_authorization:
            business_model = accessible_functions.get_function(data.provider_name, data.title).business_model

        job_serializer = RunJobSerializer(data={"arguments": data.arguments, "program": function.id})
        job_serializer.is_valid(raise_exception=True)
        return job_serializer.save(
            author=user,
            carrier=data.carrier,
            channel=data.channel,
            token=data.token,
            config=jobconfig,
            instance=data.instance,
            account_id=data.account_id,
            compute_profile=data.compute_profile,
            business_model=business_model,
        )
