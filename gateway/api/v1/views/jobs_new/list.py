"""
API V1: list jobs endpoint
"""

# pylint: disable=duplicate-code
from typing import List, Optional, cast

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status, permissions, serializers
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from api.v1.views.utils import standard_error_responses

from api.models import Job
from api.repositories.jobs import JobFilters
from api.v1.views.utils import create_paginated_response
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.views.enums.type_filter import TypeFilter
from api.use_cases.jobs.list import JobsListUseCase
from api.utils import sanitize_name
from api.models import Program


# pylint: disable=abstract-method
class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=False, default=None)
    provider = serializers.CharField(required=False, default=None)
    limit = serializers.IntegerField(
        required=False, default=settings.REST_FRAMEWORK["PAGE_SIZE"], min_value=0
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    filter = serializers.ChoiceField(
        choices=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
        required=False,
        default=None,
    )
    status = serializers.CharField(required=False, default=None)
    created_after = serializers.DateTimeField(required=False, default=None)

    def create(self, validated_data: dict):
        return JobFilters(**validated_data)

    def validate_filter(self, value: str):
        """
        Validates the type filter and converts it to TypeFilter
        """
        return TypeFilter(value) if value else None

    def validate_function(self, value: str):
        """
        Validates the function title and sanitize it
        """
        return sanitize_name(value)

    def validate_provider(self, value: str):
        """
        Validates the provider and sanitize it
        """
        return sanitize_name(value)

    def validate_status(self, value: str):
        """
        Validates the status and sanitize it
        """
        return sanitize_name(value)


class ProgramSummarySerializer(serializers.ModelSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    class Meta:
        model = Program
        fields = ["id", "title", "provider"]


class JobSerializerWithoutResult(serializers.ModelSerializer):
    """
    Job serializer. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "status", "program", "created", "sub_status"]


def serialize_output(
    jobs: List[Job],
    total_count: int,
    request,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    """
    Prepare the output for the end-point
    """
    serializer = JobSerializerWithoutResult(jobs, many=True)
    return create_paginated_response(
        data=serializer.data,
        total_count=total_count,
        request=request,
        limit=limit,
        offset=offset,
    )


@swagger_auto_schema(
    method="get",
    operation_description="List author jobs. Supports filtering via query params.",
    manual_parameters=[
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Provider name.",
        ),
        openapi.Parameter(
            "function",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Function title.",
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=False,
            default=settings.REST_FRAMEWORK["PAGE_SIZE"],
            description="Results per page.",
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=False,
            default=0,
            description="Number of results to skip.",
        ),
        openapi.Parameter(
            "filter",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            enum=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
            required=False,
            description="Job type: 'catalog' or 'serverless'.",
        ),
        openapi.Parameter(
            "status",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Filter by job status.",
        ),
        openapi.Parameter(
            "created_after",
            openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            format="date-time",
            required=False,
            description="ISO 8601 datetime; only jobs created after this.",
        ),
    ],
    responses={
        status.HTTP_200_OK: v1_serializers.JobSerializerWithoutResult(many=True),
        **standard_error_responses(
            not_found_example="Qiskit Function XXX doesn't exist.",
        ),
    },
)
@endpoint("jobs", name="jobs-list")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_jobs(request):
    """
    List jobs with optional filtering.

    Query parameters:
    - provider: provider name
    - function: function title
    - limit: Number of results to return per page
    - offset: Number of results to skip
    - type: Filter by job type ('catalog' or 'serverless')
    - status: Filter by job status
    - created_after: Filter jobs created after this datetime (ISO 8601 format)
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data

    filters = cast(JobFilters, serializer.create(validated_data))

    user = cast(AbstractUser, request.user)

    jobs, total = JobsListUseCase().execute(user=user, filters=filters)

    return Response(
        serialize_output(jobs, total, request, filters.limit, filters.offset)
    )
