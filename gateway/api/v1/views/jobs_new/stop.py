"""
Stop job endpoint
"""
from rest_framework import serializers, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.use_cases.jobs.stop import StopJobUseCase


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    service = serializers.CharField(required=False, default=None)

    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError


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

    return Response({"message": message})
