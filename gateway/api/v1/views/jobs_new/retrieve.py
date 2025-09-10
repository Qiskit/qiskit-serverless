"""
Job retrieval API endpoint
"""
from typing import cast
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.models import AbstractUser
from rest_framework import serializers, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from api import serializers as api_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.utils import sanitize_boolean
from api.use_cases.jobs.retrieve import JobRetrieveUseCase
from api.models import Job
from api.v1.views.utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    with_result = serializers.CharField(required=False, default="true")

    def validate_with_result(self, value: str):
        """
        Validates the 'with_result' param and sanitize it
        """
        return sanitize_boolean(value)

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


class JobSerializer(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]


class JobSerializerWithoutResult(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(job: Job, with_result: bool):
    """
    Prepare the output for the endpoint
    """
    if with_result:
        return JobSerializer(job).data

    return JobSerializerWithoutResult(job).data


@swagger_auto_schema(
    method="get",
    operation_description=(
        "Retrieve a specific job by ID.\n\n"
        "Use the `with_result` query parameter to include or exclude the job `result` field. "
        "Defaults to `true`."
    ),
    manual_parameters=[
        openapi.Parameter(
            name="with_result",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            default="true",
            enum=["true", "false"],
            description="Whether to include the `result` field in the response.",
        ),
    ],
    responses={
        status.HTTP_200_OK: JobSerializer,
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>", name="retrieve")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def retrieve(request, job_id):
    """
    Retrieve a specific job by ID.
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data
    with_result = validated_data["with_result"]

    user = cast(AbstractUser, request.user)

    job = JobRetrieveUseCase().execute(job_id, user, with_result)

    return Response(serialize_output(job, with_result))
