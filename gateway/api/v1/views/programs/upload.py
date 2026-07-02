"""API endpoint for uploading a Qiskit Function."""

import json
import logging
import re
from typing import Any, cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import Version, InvalidVersion
from rest_framework import permissions, serializers, status
from rest_framework import validators as validators_module
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from api.use_cases.programs.upload import UploadFunctionUseCase
from api.use_cases.programs.upload_input import UploadFunctionInput
from api.utils import check_whitelisted, sanitize_name
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider

logger = logging.getLogger("api.api.v1.views.programs.upload")


class ProgramSerializer(serializers.ModelSerializer):
    """Serializer for uploading (creating or updating) a Qiskit Function."""

    entrypoint = serializers.CharField(required=False)
    image = serializers.CharField(required=False)
    provider = serializers.CharField(required=False)
    runner = serializers.CharField(required=False)

    class Meta:
        model = Program
        fields = [
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "env_vars",
            "image",
            "provider",
            "description",
            "type",
            "version",
            "runner",
        ]
        ref_name = "ProgramsUploadProgram"

    def get_validators(self):
        """Exclude UniqueConstraint validators — upsert logic lives in the use case."""
        return [v for v in super().get_validators() if not isinstance(v, validators_module.UniqueTogetherValidator)]

    def validate_title(self, value):
        """Sanitize title."""
        return sanitize_name(value)

    def validate_provider(self, value):
        """Sanitize provider name."""
        return sanitize_name(value) if value else value

    def validate_entrypoint(self, value):
        """Validate the entrypoint is a safe, relative ``.py`` file path.

        The entrypoint is inserted into the runner's execution command
        (e.g. ``python {entrypoint}`` for Ray) and into COS/PDS object paths, so
        it must not contain shell metacharacters, be absolute, or traverse
        outside the function directory via ``..``.
        """
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValidationError(
                "Invalid entrypoint. It must be a relative path to a .py file "
                "without '..' segments or shell characters."
            )
        segments = value.split("/")
        if not re.fullmatch(r"[A-Za-z0-9_./-]+\.py", value) or value.startswith("/") or ".." in segments:
            raise ValidationError(
                "Invalid entrypoint. It must be a relative path to a .py file "
                "without '..' segments or shell characters."
            )
        return value

    def validate_image(self, value):
        """Validate image."""
        return value

    def _parse_dependency(self, dep: Any):
        if not isinstance(dep, dict) and not isinstance(dep, str):
            raise ValidationError("'dependencies' should be an array with strings or dict.")

        if isinstance(dep, str):
            dep_string = dep
        else:
            dep_name = list(dep.keys())
            if len(dep_name) > 1 or len(dep_name) == 0:
                raise ValidationError("'dependencies' should be an array with dict containing one dependency only.")
            dep_name = str(dep_name[0])
            dep_version = str(list(dep.values())[0])

            try:
                if int(dep_version[0]) >= 0:
                    dep_version = f"=={dep_version}"
            except ValueError:
                pass

            dep_string = dep_name + dep_version

        requirement = Requirement(dep_string)
        req_specifier_list = list(requirement.specifier)
        req_specifier_first = next(iter(req_specifier_list), None)

        if len(req_specifier_list) > 1 or (req_specifier_first and req_specifier_first.operator != "=="):
            raise ValidationError("'dependencies' needs one fixed version using the '==' operator.")

        return requirement

    def _validate_deps(self, deps):
        if not isinstance(deps, list):
            raise ValidationError("'dependencies' should be an array.")

        if len(deps) == 0:
            return

        try:
            required_deps = [self._parse_dependency(dep) for dep in deps]
        except InvalidRequirement as invalid_requirement:
            raise ValidationError("Error while parsing dependencies.") from invalid_requirement

        try:
            check_whitelisted(required_deps)
        except ValueError as value_error:
            raise ValidationError(value_error.args[0]) from value_error

    def validate(self, attrs):  # pylint: disable=too-many-branches
        """Validates serializer data."""
        entrypoint = attrs.get("entrypoint", None)
        image = attrs.get("image", None)
        if entrypoint is None and image is None:
            raise ValidationError("At least one of attributes (entrypoint, image) is required.")
        try:
            deps = json.loads(attrs.get("dependencies", "[]"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError(
                "'dependencies' should be an array of strings or objects: "
                "`['pendulum==3.0.0', '...'] or [{'pendulum':'3.0.0'}, {...}]`"
            ) from exc

        self._validate_deps(deps)

        title = attrs.get("title")
        provider = attrs.get("provider", None)
        if provider and "/" in title:
            raise ValidationError("Provider defined in title and in provider fields.")

        title_split = title.split("/")
        if len(title_split) > 2:
            raise ValidationError("Qiskit Function title is malformed. It can only contain one slash.")

        if image is not None:
            if provider is None and len(title_split) != 2:
                raise ValidationError("Custom images are only available if you are a provider.")
            if not provider:
                provider = title_split[0]
            provider_instance = Provider.objects.filter(name=provider).first()
            if provider_instance is None:
                raise ValidationError(f"{provider} is not valid provider.")
            if provider_instance.registry and not image.startswith(provider_instance.registry):
                raise ValidationError(f"Custom images must be in {provider_instance.registry}.")

        version = attrs.get("version", None)
        if version is not None:
            try:
                Version(version)
            except InvalidVersion as exc:
                raise ValidationError("Invalid version - expected format x.y.z") from exc

        return super().validate(attrs)


@swagger_auto_schema(
    method="post",
    operation_description="Upload a Qiskit Function",
    request_body=ProgramSerializer,
    responses={status.HTTP_200_OK: ProgramSerializer},
)
@endpoint("programs/upload", method="POST", name="programs-upload")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def upload_program(request: Request) -> Response:
    """Upload or update a Qiskit Function."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)

    serializer = ProgramSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = UploadFunctionInput.from_validated_data(serializer.validated_data)

    logger.info(
        "[programs-upload] user_id=%s title=%s provider=%s accessible_functions=%s",
        user.id,
        data.title,
        data.provider,
        accessible_functions,
    )

    function = UploadFunctionUseCase().execute(user, accessible_functions, data)
    logger.info("[programs-upload] user_id=%s program=%s | Function uploaded ok", user.id, function.title)
    return Response(ProgramSerializer(function).data)
