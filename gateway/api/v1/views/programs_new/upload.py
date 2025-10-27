"""
API endpoint for upload a function.
"""

# pylint: disable=duplicate-code, abstract-method

import json
import logging
from typing import Any, cast

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from rest_framework import permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import Program
from api.use_cases.functions.upload import UploadFunctionData, FunctionUploadUseCase
from api.utils import encrypt_env_vars
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.serializer_utils import SanitizedCharField

logger = logging.getLogger("gateway.views.programs.upload")


def get_upload_path(instance, filename):
    """Returns save path for artifacts."""
    return f"{instance.author.username}/{instance.id}/{filename}"


# TODO: review validation inheritances such as dependencies
class InputSerializer(serializers.Serializer):
    """
    Validates and sanitizes query parameters for the jobs list endpoint.
    """

    title = SanitizedCharField(required=True)
    provider = SanitizedCharField(required=False, default=None)

    entrypoint = serializers.CharField(required=False, default=None)
    image = serializers.CharField(required=False, default=None)

    arguments = serializers.CharField(required=False, default=None)
    dependencies = serializers.JSONField(required=False, default=list)
    env_vars = serializers.JSONField(required=False, default=dict)
    description = serializers.CharField(required=False, default=None)

    artifact = serializers.FileField(required=False, default=None)

    def _normalize_dependency(self, raw_dependency):
        if isinstance(raw_dependency, str):
            return raw_dependency

        dependency_name = list(raw_dependency.keys())[0]
        dependency_version = str(list(raw_dependency.values())[0])

        # if starts with a number then prefix ==
        try:
            if int(dependency_version[0]) >= 0:
                dependency_version = f"=={dependency_version}"
        except ValueError:
            logger.debug(
                "Dependency (%s) version (%s) does not start with a number, "
                "assuming an operator (==, >=, ~=...) or empty",
                dependency_name,
                dependency_version,
            )

        return dependency_name + dependency_version

    def validate_dependencies(self, value: list):
        """
        Validates the function title
        """
        if not isinstance(value, list):
            raise serializers.ValidationError("'dependencies' should be a list.")

        return [self._normalize_dependency(dep) for dep in value]

    def validate_artifact(self, value):
        """
        Validates the uploaded artifact
        """
        if value is None:
            return value

        try:
            FileExtensionValidator(allowed_extensions=["tar"])(value)
        except ValidationError as exc:
            raise serializers.ValidationError(
                "'artifact' should be a 'tar' file"
            ) from exc


        return value
    
    def validate(self, attrs):
        super().validate(attrs)

        title = attrs.get("title")
        provider = attrs.get("provider")

        image = attrs.get("image")

        env_vars = attrs.get("env_vars")

        title_split = title.split("/")
        if not provider:
            # Check if title contains the provider: <provider>/<title>
            logger.debug("Provider is None, check if it is in the title.")
            if len(title_split) > 2:
                raise ValidationError(
                    "Qiskit Function title is malformed. It can only contain one slash."
                )
            if len(title_split) > 1:
                attrs["provider"] = title_split[0]
                attrs["title"] = title_split[1]

        else:
            if len(title_split) > 1:
                raise ValidationError(
                    "Qiskit Function title is malformed. It cannot contain title with slash and provider."
                )

        if env_vars:
            attrs["env_vars"] = encrypt_env_vars(env_vars)

        if image is not None and attrs["provider"] is None:
            raise ValidationError(
                "Custom images are only available if you are a provider."
            )
        
        return attrs


    def create(self, validated_data):
        title = validated_data.get("title")
        provider = validated_data.get("provider")

        entrypoint = validated_data.get("entrypoint")
        image = validated_data.get("image")

        arguments = validated_data.get("arguments")
        dependencies = validated_data.get("dependencies")
        env_vars = validated_data.get("env_vars")
        description = validated_data.get("description")

        return UploadFunctionData(
            function_title=title,
            provider=provider,
            entrypoint=entrypoint,
            image=image,
            arguments=arguments,
            dependencies=json.dumps(dependencies),
            env_vars=json.dumps(env_vars),
            description=description,
        )


# class ProgramSummarySerializer(serializers.ModelSerializer):
#     """
#     Summary fields for the related program.
#     """

#     class Meta:
#         model = Program
#         fields = ["id", "title", "provider"]


# class JobSerializerWithoutResult(serializers.ModelSerializer):
#     """
#     Minimal job representation for listings.
#     """

#     program = ProgramSummarySerializer(many=False)

#     class Meta:
#         model = Job
#         fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(
    program: Program
) -> dict[str, Any]:
    """
    Build a paginated response with serialized jobs.

    Args:
        jobs: List of job instances.
        total_count: Total number of jobs matching the filters.
        request: The HTTP request (used to build pagination links).
        limit: Page size used for pagination.
        offset: Offset used for pagination.

    Returns:
        A dictionary with pagination metadata and serialized items.
    """
    return {
        "id": program.id,
        "title": program.title,
        "type": program.type,
        "description": program.description,
        "image": program.image,
        "env_vars": program.env_vars,
        "dependencies": program.dependencies,
        "provider": program.provider.name if program.provider else None,
    }


# @swagger_auto_schema(
#     method="get",
#     operation_description="List author jobs. Supports filtering via query params.",
#     manual_parameters=[
#         openapi.Parameter(
#             "provider",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_STRING,
#             required=False,
#             description="Provider name.",
#         ),
#         openapi.Parameter(
#             "function",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_STRING,
#             required=False,
#             description="Function title.",
#         ),
#         openapi.Parameter(
#             "limit",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_INTEGER,
#             required=False,
#             default=settings.REST_FRAMEWORK["PAGE_SIZE"],
#             description="Results per page.",
#         ),
#         openapi.Parameter(
#             "offset",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_INTEGER,
#             required=False,
#             default=0,
#             description="Number of results to skip.",
#         ),
#         openapi.Parameter(
#             "filter",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_STRING,
#             enum=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
#             required=False,
#             description="Job type: 'catalog' or 'serverless'.",
#         ),
#         openapi.Parameter(
#             "status",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_STRING,
#             required=False,
#             description="Filter by job status.",
#         ),
#         openapi.Parameter(
#             "created_after",
#             openapi.IN_QUERY,
#             type=openapi.TYPE_STRING,
#             format="date-time",
#             required=False,
#             description="ISO 8601 datetime; only jobs created after this.",
#         ),
#     ],
#     responses={
#         status.HTTP_200_OK: JobSerializerWithoutResult(many=True),
#         **standard_error_responses(
#             not_found_example="Qiskit Function XXX doesn't exist.",
#         ),
#     },
# )
@endpoint("programs/upload", name="programs-upload")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def upload(request: Request) -> Response:
    """
    Uploads a program.

    Query params:
        - provider: Provider name.
        - function: Function title.
        - limit: Page size.
        - offset: Items to skip.
        - filter: 'catalog' | 'serverless'.
        - status: Job status.
        - created_after: ISO 8601 datetime cutoff.

    Returns:
        A paginated list of jobs matching the filters.
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = cast(UploadFunctionData, serializer.create(serializer.validated_data))
    user = cast(AbstractUser, request.user)

    program = FunctionUploadUseCase().execute(author=user, data=data)
    return Response(serialize_output(program))
