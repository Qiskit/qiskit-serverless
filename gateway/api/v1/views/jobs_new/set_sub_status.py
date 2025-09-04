"""
Update sub status endpoint
"""
from typing import cast
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.models import AbstractUser
from rest_framework import serializers, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api.v1.endpoint_decorator import endpoint
from api import serializers as api_serializers
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.models import Job
from api.use_cases.jobs.set_sub_status import SetJobSubStatusUseCase


class InputSerializer(serializers.Serializer):
    """
    Serializer for input endpoint
    """

    sub_status = serializers.ChoiceField(
        choices=Job.RUNNING_SUB_STATUSES,
        required=True,
        error_messages={
            "required": "'sub_status' not provided or is not valid",
            "invalid_choice": "'sub_status' not provided or is not valid",
            "null": "'sub_status' cannot be null",
            "blank": "'sub_status' cannot be blank",
        },
    )

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


class ProgramSummarySerializer(api_serializers.ProgramSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    class Meta(api_serializers.ProgramSerializer.Meta):
        fields = ["id", "title", "provider"]


class JobSerializerWithoutResult(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(job: Job):
    """
    Prepare the output for the endpoint
    """
    return {"job": JobSerializerWithoutResult(job).data}


@swagger_auto_schema(
    method="patch",
    operation_description="Update the sub status of a job",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: JobSerializerWithoutResult(many=False),
        status.HTTP_400_BAD_REQUEST: openapi.Response(
            description="In case your request doesnt have a valid 'sub_status'.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="'sub_status' not provided or is not valid",
                    )
                },
            ),
        ),
        status.HTTP_403_FORBIDDEN: openapi.Response(
            description="In case you cannot change the sub_status.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING,
                        example="Cannot update 'sub_status' when is not in RUNNING status. "
                        "(Currently PENDING",
                    )
                },
            ),
        ),
        status.HTTP_404_NOT_FOUND: openapi.Response(
            description="In case the job doesnt exist or you dont have access to it.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING, example="Job [XXXX] not found"
                    )
                },
            ),
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/sub_status", name="jobs-sub-status")
@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def set_sub_status(request, job_id):
    """
    Update job sub status
    """
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    sub_status = serializer.validated_data["sub_status"]
    user = cast(AbstractUser, request.user)

    job = SetJobSubStatusUseCase().execute(job_id, user, sub_status)

    return Response(serialize_output(job))
