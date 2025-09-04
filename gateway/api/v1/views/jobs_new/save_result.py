"""
Save result for a job API endpoint
"""
# pylint: disable=duplicate-code
from typing import cast
from django.contrib.auth.models import AbstractUser
from rest_framework import serializers, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api import serializers as api_serializers
from api.use_cases.jobs.save_result import JobSaveResultUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.models import Job


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    result = serializers.DictField(required=True)

    # pylint: disable=duplicate-code
    def create(self, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError

    def update(self, instance, validated_data):
        """Not implemented - this serializer is for validation only."""
        raise NotImplementedError


class ProgramSerializer(api_serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(api_serializers.ProgramSerializer.Meta):
        # pylint: disable=duplicate-code
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


class JobSerializer(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]


def serialize_output(job: Job):
    """
    Prepare the output for the endpoint
    """
    return JobSerializer(job).data


@endpoint("jobs/<uuid:job_id>/result", name="retrieve")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def save_result(request, job_id):
    """
    Save result for a job
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = serializer.validated_data["result"]
    user = cast(AbstractUser, request.user)

    job = JobSaveResultUseCase().execute(job_id, user, result)

    return Response(serialize_output(job))
