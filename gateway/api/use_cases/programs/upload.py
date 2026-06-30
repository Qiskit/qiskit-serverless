"""Use case: upload (create or update) a Qiskit Function."""

import json
import logging

from django.contrib.auth.models import AbstractUser
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.access_policies.programs import ProgramAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.upload_input import UploadFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    CodeEngineProject,
    DEFAULT_PROGRAM_ENTRYPOINT,
    Program as Function,
    Provider,
)
from core.utils import encrypt_env_vars

logger = logging.getLogger("api.api.use_cases.programs.upload")


def _normalize_dependency(raw_dependency) -> str:
    if isinstance(raw_dependency, str):
        return raw_dependency

    dependency_name = list(raw_dependency.keys())[0]
    dependency_version = str(list(raw_dependency.values())[0])

    try:
        if int(dependency_version[0]) >= 0:
            dependency_version = f"=={dependency_version}"
    except ValueError:
        pass

    return dependency_name + dependency_version


class UploadFunctionUseCase:
    """Use case for uploading (creating or updating) a Qiskit Function."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        data: UploadFunctionInput,
    ) -> Function:
        """Create or update a Qiskit Function.

        Raises FunctionNotFoundException when the user lacks permission.
        """
        provider_obj = None
        if data.provider:
            provider_obj = Provider.objects.filter(name=data.provider).first()
            if provider_obj is None or not ProviderAccessPolicy.can_upload_function(
                user, provider_obj, data.title, accessible_functions
            ):
                raise FunctionNotFoundException(function=data.title, provider=data.provider)
            existing = Function.objects.filter(title=data.title, provider__name=data.provider).first()
        else:
            if not ProgramAccessPolicies.can_create(user, accessible_functions):
                raise FunctionNotFoundException(function=data.title, provider=None)
            existing = Function.objects.filter(title=data.title, author=user).first()

        if existing is None:
            return self._create(data, user=user, provider=provider_obj)
        return self._update(existing, data, user=user)

    def _create(self, data: UploadFunctionInput, user, provider) -> Function:
        logger.info("user_id=%s program=%s | Creating function", user.id, data.title)

        if data.entrypoint is None and data.image is None:
            raise DRFValidationError("At least one of attributes (entrypoint, image) is required.")

        env_vars = data.env_vars
        if env_vars:
            env_vars = json.dumps(encrypt_env_vars(json.loads(env_vars)))

        raw_deps = json.loads(data.dependencies or "[]")
        dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])

        function = Function(
            title=data.title,
            author=user,
            provider=provider,
            runner=data.runner or Function.RAY,
            entrypoint=data.entrypoint or DEFAULT_PROGRAM_ENTRYPOINT,
            artifact=data.artifact,
            image=data.image,
            env_vars=env_vars or {},
            dependencies=dependencies,
            description=data.description,
            version=data.version,
        )
        if data.type is not None:
            function.type = data.type
        if data.arguments_schema is not None:
            function.arguments_schema = data.arguments_schema

        CodeEngineProject.objects.assign_to_program(function)
        if function.runner == Function.FLEETS and not function.code_engine_project:
            raise DRFValidationError("No active Code Engine project available. Contact administrator.")
        function.save()
        return function

    def _update(self, instance: Function, data: UploadFunctionInput, user) -> Function:
        logger.info("user_id=%s program=%s | Updating function", user.id, instance.title)

        instance.entrypoint = data.entrypoint or DEFAULT_PROGRAM_ENTRYPOINT
        if data.dependencies is not None:
            raw_deps = json.loads(data.dependencies)
            instance.dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])
        if data.env_vars is not None:
            instance.env_vars = json.dumps(encrypt_env_vars(json.loads(data.env_vars)))
        instance.artifact = data.artifact
        instance.author = user
        instance.image = data.image
        if data.runner is not None:
            instance.runner = data.runner

        if data.description is not None:
            instance.description = data.description
        if data.version is not None:
            instance.version = data.version
        if data.arguments_schema is not None:
            instance.arguments_schema = data.arguments_schema

        CodeEngineProject.objects.assign_to_program(instance)
        instance.save()
        return instance
