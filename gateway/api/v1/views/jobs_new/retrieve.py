"""
API endpoint for retrieving a job by ID.
"""
# pylint: disable=duplicate-code, abstract-method

from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api import serializers as api_serializers
from api.models import Job
from api.use_cases.jobs.retrieve import JobRetrieveUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validates query parameters for job retrieval.
    """

    with_result = serializers.BooleanField(required=False, default=True)


class ProgramSerializer(api_serializers.ProgramSerializer):
    """
    Program fields for detailed job responses.
    """

    class Meta(api_serializers.ProgramSerializer.Meta):
        fields = [
            "id",
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "provider",
            "description",
            "documentation_url",
            "type",
        ]


class JobSerializer(api_serializers.JobSerializer):
    """
    Job representation including the `result` and full `program`.
    """

    program = ProgramSerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]


class ProgramSummary(ProgramSerializer):
    """Minimal representation of a program"""

    class Meta(api_serializers.ProgramSerializer.Meta):
        fields = ["id", "title", "provider"]


class JobSerializerWithoutResult(api_serializers.JobSerializer):
    """
    Minimal job representation without `result`, keeping nested `program`.
    """

    program = ProgramSummary(read_only=True)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(job: Job, with_result: bool) -> Job:
    """
    Serialize the job according to the `with_result` flag.

    Args:
        job: Job instance to serialize.
        with_result: Whether to include the `result` field.

    Returns:
        Serialized job as a dict.
    """
    if with_result:
        return JobSerializer(job).data
    return JobSerializerWithoutResult(job).data


@swagger_auto_schema(
    method="get",
    operation_description=(
        "Retrieve a specific job by ID.\n\n"
        "Use the `with_result` query parameter to include or exclude the job `result` field. "
        "Defaults to `true`."
    ),
    manual_parameters=[
        openapi.Parameter(
            name="with_result",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            default="true",
            enum=["true", "false"],
            description="Whether to include the `result` field in the response.",
        ),
    ],
    responses={
        status.HTTP_200_OK: JobSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>", name="retrieve")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def retrieve(request: Request, job_id: UUID) -> Response:
    """
    Retrieve a job by its UUID.

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).

    Returns:
        A serialized job, optionally including `result`.
    """
    params = InputSerializer(data=request.query_params)
    params.is_valid(raise_exception=True)
    with_result: bool = params.validated_data["with_result"]

    user = cast(AbstractUser, request.user)
    job = JobRetrieveUseCase().execute(job_id, user, with_result)

    return Response(serialize_output(job, with_result))
