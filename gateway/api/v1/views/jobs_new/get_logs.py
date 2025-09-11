"""
API endpoint for retrieving job logs.
"""

# pylint: disable=duplicate-code, abstract-method

from typing import Any, cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.utils import standard_error_responses


class JobLogsOutputSerializer(serializers.Serializer):
    """
    Serializer for job logs response.
    """

    logs = serializers.CharField()


def serialize_output(logs: str) -> dict[str, Any]:
    """
    Serialize logs into the standard response format.

    Args:
        logs: The job logs as a string.

    Returns:
        A dictionary with the serialized logs.
    """
    return JobLogsOutputSerializer({"logs": logs}).data


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve logs for a given job.",
    responses={
        status.HTTP_200_OK: JobLogsOutputSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/logs", name="jobs-logs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_logs(request, job_id) -> Response:
    """
    Retrieve logs for a specific job.

    Args:
        request: The HTTP request object.
        job_id: The UUID of the job (path parameter).

    Returns:
        Response containing the serialized job logs.
    """
    user = cast(AbstractUser, request.user)
    logs = GetJobLogsUseCase().execute(job_id, user)
    return Response(serialize_output(logs))
