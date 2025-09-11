"""
API endpoint to update a job's sub-status.
"""
# pylint: disable=abstract-method

from typing import Any, cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api import serializers as api_serializers
from api.models import Job
from api.use_cases.jobs.set_sub_status import SetJobSubStatusUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validates the request body for updating the sub-status.
    """

    sub_status = serializers.ChoiceField(
        choices=Job.RUNNING_SUB_STATUSES,
        required=True,
        error_messages={
            "required": "'sub_status' not provided or is not valid",
            "invalid_choice": "'sub_status' not provided or is not valid",
            "null": "'sub_status' cannot be null",
            "blank": "'sub_status' cannot be blank",
        },
    )


class ProgramSummarySerializer(api_serializers.ProgramSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    class Meta(api_serializers.ProgramSerializer.Meta):
        fields = ["id", "title", "provider"]


class JobSerializerWithoutResult(api_serializers.JobSerializer):
    """
    Job representation without `result`.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(job: Job) -> dict[str, Any]:
    """
    Build the response payload.

    Args:
        job: Updated job instance.

    Returns:
        A dictionary containing the serialized job under the 'job' key.
    """
    return {"job": JobSerializerWithoutResult(job).data}


@swagger_auto_schema(
    method="patch",
    operation_description="Update the sub status of a job",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: JobSerializerWithoutResult(many=False),
        **standard_error_responses(
            bad_request_example="'sub_status' not provided or is not valid",
            forbidden_example="Cannot update 'sub_status' when job is not RUNNING.",
            not_found_example="Job [XXXX] not found",
            unauthorized_example="Authentication credentials were not provided or are invalid.",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/sub_status", name="jobs-sub-status")
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def set_sub_status(request: Request, job_id: UUID) -> Response:
    """
    Update the sub-status for the specified job.

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).

    Returns:
        Response containing the updated job under the 'job' key.
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    sub_status = serializer.validated_data["sub_status"]
    user = cast(AbstractUser, request.user)

    job = SetJobSubStatusUseCase().execute(job_id, user, sub_status)

    return Response(serialize_output(job))
