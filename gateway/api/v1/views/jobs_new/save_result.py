"""
Save result for a job API endpoint
"""
# pylint: disable=duplicate-code, abstract-method

from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api import serializers as api_serializers
from api.models import Job
from api.use_cases.jobs.save_result import JobSaveResultUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    result = serializers.CharField(required=True)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobsSaveResultInputSerializer"


class ProgramSerializer(api_serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
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
        ref_name = "JobsSaveResultProgramSerializer"


class JobSerializer(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]
        ref_name = "JobsSaveResultJobSerializer"


def serialize_output(job: Job):
    """
    Serialize the job for the response.

    Args:
        job: The updated job instance.

    Returns:
        Serialized job as a dictionary.
    """
    return JobSerializer(job).data


@swagger_auto_schema(
    method="post",
    operation_description="Save the result for a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: JobSerializer(many=False),
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/result", name="jobs-result")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def save_result(request: Request, job_id: UUID) -> Response:
    """
    Save a result payload into the specified job.

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).

    Returns:
        Response containing the updated serialized job.
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = serializer.validated_data["result"]
    user = cast(AbstractUser, request.user)

    job = JobSaveResultUseCase().execute(job_id, user, result)

    return Response(serialize_output(job))
