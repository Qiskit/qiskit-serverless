"""Use case: upload (create or update) a Qiskit Function."""

import json
import logging

from django.contrib.auth.models import AbstractUser
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.access_policies.programs import ProgramAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.v1.serializers import UploadProgramSerializer
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
        request_data: dict,
    ) -> Function:
        """Create or update a Qiskit Function.

        Validates the request data, checks permissions, and saves the function.
        Raises FunctionNotFoundException when the user lacks permission.
        """
        serializer = UploadProgramSerializer(data=request_data)
        serializer.is_valid(raise_exception=True)

        title_raw = serializer.validated_data.get("title")
        provider_raw = serializer.validated_data.get("provider", None)
        provider_name, title = serializer.get_provider_name_and_title(provider_raw, title_raw)

        provider_obj = None
        if provider_name:
            provider_obj = Provider.objects.filter(name=provider_name).first()
            if provider_obj is None or not ProviderAccessPolicy.can_upload_function(
                user, provider_obj, title, accessible_functions
            ):
                raise FunctionNotFoundException(function=title, provider=provider_name)
            existing = Function.objects.filter(title=title, provider__name=provider_name).first()
        else:
            if not ProgramAccessPolicies.can_create(user, accessible_functions):
                raise FunctionNotFoundException(function=title, provider=None)
            existing = Function.objects.filter(title=title, author=user).first()

        if existing is not None:
            serializer = UploadProgramSerializer(existing, data=request_data)
            serializer.is_valid(raise_exception=True)

        runner = serializer.validated_data.get("runner", Function.RAY)
        validated = serializer.validated_data

        if existing is None:
            return self._create(validated, user=user, title=title, provider=provider_obj, runner=runner)
        return self._update(existing, validated, user=user, runner=runner)

    def _create(self, validated_data: dict, user, title: str, provider, runner: str) -> Function:
        logger.info("user_id=%s program=%s | Creating function", user.id, title)

        env_vars = validated_data.get("env_vars")
        if env_vars:
            env_vars = json.dumps(encrypt_env_vars(json.loads(env_vars)))

        raw_deps = json.loads(validated_data.get("dependencies", "[]"))
        dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])

        function = Function(
            title=title,
            author=user,
            provider=provider,
            runner=runner,
            entrypoint=validated_data.get("entrypoint", DEFAULT_PROGRAM_ENTRYPOINT),
            artifact=validated_data.get("artifact"),
            image=validated_data.get("image"),
            env_vars=env_vars or {},
            dependencies=dependencies,
            description=validated_data.get("description"),
            version=validated_data.get("version"),
        )
        if "type" in validated_data:
            function.type = validated_data["type"]

        CodeEngineProject.objects.assign_to_program(function)
        if function.runner == Function.FLEETS and not function.code_engine_project:
            raise DRFValidationError("No active Code Engine project available. Contact administrator.")
        function.save()
        return function

    def _update(self, instance: Function, validated_data: dict, user, runner: str) -> Function:
        logger.info("user_id=%s program=%s | Updating function", user.id, instance.title)

        instance.entrypoint = validated_data.get("entrypoint", DEFAULT_PROGRAM_ENTRYPOINT)
        raw_deps = json.loads(validated_data.get("dependencies", "[]"))
        instance.dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])
        instance.env_vars = validated_data.get("env_vars", {})
        instance.artifact = validated_data.get("artifact")
        instance.author = user
        instance.image = validated_data.get("image")

        description = validated_data.get("description")
        if description is not None:
            instance.description = description

        version = validated_data.get("version")
        if version is not None:
            instance.version = version

        instance.runner = runner
        CodeEngineProject.objects.assign_to_program(instance)
        instance.save()
        return instance
