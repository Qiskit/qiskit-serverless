"""
Get job logs API endpoint
"""
# pylint: disable=duplicate-code
from typing import cast
from django.contrib.auth.models import AbstractUser
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api.use_cases.jobs.get_logs import GetJobLogsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions


def serialize_output(logs: str):
    """
    Prepare the output for the endpoint
    """
    return {"logs": logs}


@endpoint("jobs/<uuid:job_id>/logs", name="jobs-logs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_logs(request, job_id):
    """
    Get job logs
    """
    user = cast(AbstractUser, request.user)
    logs = GetJobLogsUseCase().execute(job_id, user)

    return Response(serialize_output(logs))
