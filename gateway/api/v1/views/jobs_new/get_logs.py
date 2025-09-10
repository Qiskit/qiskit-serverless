"""
Get job logs API endpoint
"""
# pylint: disable=duplicate-code
from typing import cast
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
    Output serializer for get logs endpoint
    """

    logs = serializers.CharField()

    def create(self, validated_data):
        raise NotImplementedError

    def update(self, instance, validated_data):
        raise NotImplementedError


def serialize_output(logs: str):
    """
    Prepare the output for the endpoint
    """
    return JobLogsOutputSerializer({"logs": logs}).data


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve logs for a given job.",
    responses={
        status.HTTP_200_OK: JobLogsOutputSerializer,
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
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
