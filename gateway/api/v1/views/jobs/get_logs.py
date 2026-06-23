"""
API endpoint for retrieving job logs.
"""

# pylint: disable=duplicate-code, abstract-method

import logging
from typing import Any, cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.http import HttpResponseRedirect
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses

logger = logging.getLogger("api.api.v1.views.jobs.get_logs")


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
@endpoint("jobs/<uuid:job_id>/logs", method="GET", name="jobs-logs")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_logs(request: Request, job_id: UUID) -> Response:
    """
    Retrieve logs for a specific job.

    Args:
        request: The HTTP request object.
        job_id: The UUID of the job (path parameter).

    Returns:
        302 redirect to presigned COS URL (Fleet, logs ready),
        204 No Content (Fleet, no logs yet),
        or 200 JSON with logs field (Ray).
    """
    user = cast(AbstractUser, request.user)
    result = GetJobLogsUseCase().execute(job_id, user)

    if result.redirect_url:
        logger.info("[jobs-logs] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
        return HttpResponseRedirect(result.redirect_url)

    if result.raw_log is None:
        return Response(status=status.HTTP_204_NO_CONTENT)

    logger.info("[jobs-logs] user_id=%s job_id=%s | Logs retrieved ok", user.id, job_id)
    return Response(serialize_output(result.raw_log))
