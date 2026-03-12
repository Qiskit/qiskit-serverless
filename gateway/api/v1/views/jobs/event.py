"""
Creates a job event.
"""

# pylint: disable=duplicate-code, abstract-method

from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.event import EventData, JobEventUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.model_managers.job_events import JobEventType

VALID_TYPES = [JobEventType.ERROR]


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    type = serializers.CharField(required=True)
    code = serializers.CharField(required=True)
    message = serializers.CharField(required=True)
    args = serializers.JSONField(required=False)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobEventInputSerializer"

    def validate_type(self, value: str):
        """
        Validates the job event type
        """
        value_upper = value.upper()
        if value_upper not in VALID_TYPES:
            raise ValidationError("Type is not valid. Valid types: {VALID_TYPES}")

        return value_upper

    def create(self, validated_data):
        event_type = validated_data.get("type")
        code = validated_data.get("code")
        message = validated_data.get("message")
        args = validated_data.get("args")

        return EventData(event_type=event_type, code=code, message=message, args=args)


@swagger_auto_schema(
    method="post",
    operation_description="Creates an event for a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: None,
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/event")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def event(request: Request, job_id: UUID) -> Response:
    """
    Creates an error event for the selected job

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).

    Returns:
        None.
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    data = serializer.create(serializer.validated_data)
    user = cast(AbstractUser, request.user)

    JobEventUseCase().execute(job_id, user, data)

    return Response(None)
