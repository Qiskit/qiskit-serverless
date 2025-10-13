"""
Stop job endpoint
"""
# pylint: disable=abstract-method
from rest_framework import serializers, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from drf_yasg.utils import swagger_auto_schema
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.use_cases.jobs.stop import StopJobUseCase
from api.v1.views.swagger_utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    service = serializers.CharField(required=False, default=None)


class StopJobOutputSerializer(serializers.Serializer):
    """
    Output serializer for the stop job endpoint.
    """

    message = serializers.CharField()


def serialize_output(message: str) -> StopJobOutputSerializer:
    """
    Serialize output for stop endpoint
    """
    return StopJobOutputSerializer({"message": message}).data


@swagger_auto_schema(
    method="post",
    operation_description="Stop a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: StopJobOutputSerializer,
        **standard_error_responses(
            bad_request_example="'service' not provided or is not valid",
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/stop", name="jobs-stop")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def stop(request, job_id):
    """
    Stop job
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data
    service = validated_data["service"]

    message = StopJobUseCase().execute(job_id, service)

    return Response(serialize_output(message))
