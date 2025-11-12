"""
API endpoint for retrieving job logs.
"""

# pylint: disable=duplicate-code, abstract-method

from typing import Any, cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.provider_logs import GetProviderJobLogsUseCase
from api.use_cases.jobs.put_provider_logs import PutProviderJobLogsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    log = serializers.CharField(required=True)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobProviderLogsInputSerializer"

class JobProviderLogsOutputSerializer(serializers.Serializer):
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
    return JobProviderLogsOutputSerializer({"logs": logs}).data


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve logs for a given job as provider.",
    responses={
        status.HTTP_200_OK: JobProviderLogsOutputSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/provider-logs", name="jobs-provider-logs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def provider_logs(request: Request, job_id: UUID) -> Response:
    """
    Retrieve logs for a specific job.

    Args:
        request: The HTTP request object.
        job_id: The UUID of the job (path parameter).

    Returns:
        Response containing the serialized job logs.
    """

    user = cast(AbstractUser, request.user)

    #GET
    if request.method == "GET":
        logs = GetProviderJobLogsUseCase().execute(job_id, user)
        return Response(serialize_output(logs))
    

    # PUT
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    log = serializer.validated_data["log"]
    PutProviderJobLogsUseCase().execute(job_id, user, log)