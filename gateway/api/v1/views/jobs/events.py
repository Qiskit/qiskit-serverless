"""
API endpoint for retrieving job logs.
"""

# pylint: disable=duplicate-code, abstract-method

from typing import Any, cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.events import JobsEventsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.model_managers.job_events import JobEventType
from core.models import JobEvent

VALID_TYPES = [JobEventType.ERROR]


class InputSerializer(serializers.Serializer):
    """
    Validates query parameters for job retrieval.
    """

    type = serializers.CharField(required=False)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobEventsInputSerializer"

    def validate_type(self, value: str):
        """
        Validates the function title
        """
        value_upper = value.upper()
        if value_upper not in VALID_TYPES:
            raise ValidationError("Type is not valid. Valid types: {VALID_TYPES}")

        return value_upper


class JobEventOutputSerializer(serializers.ModelSerializer):
    """
    Serializer for job logs response.
    """

    class Meta:
        model = JobEvent
        fields = [
            "event_type",
            "origin",
            "context",
            "created",
            "data",
        ]


def serialize_output(events: JobEvent) -> dict[str, Any]:
    """
    Serialize events into the standard response format.

    Args:
        events: The job events as a string.

    Returns:
        A dictionary with the serialized events.
    """
    return JobEventOutputSerializer(events, many=True).data


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve events for a given job.",
    responses={
        status.HTTP_200_OK: JobEventOutputSerializer,
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/events", name="jobs-events")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_logs(request: Request, job_id: UUID) -> Response:
    """
    Retrieve logs for a specific job.

    Args:
        request: The HTTP request object.
        job_id: The UUID of the job (path parameter).

    Returns:
        Response containing the serialized job logs.
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    event_type = serializer.validated_data.get("type")

    user = cast(AbstractUser, request.user)
    events = JobsEventsUseCase().execute(job_id, user, event_type)
    return Response(serialize_output(events))
