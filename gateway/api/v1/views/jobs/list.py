"""
API endpoint for listing jobs with optional filters and pagination.
"""

# pylint: disable=duplicate-code, abstract-method

from typing import cast

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from core.models import Job, Program
from api.repositories.jobs import JobFilters
from api.use_cases.jobs.list import JobsListUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.utils import (
    PaginatedResponse,
    create_paginated_response,
)
from api.v1.views.swagger_utils import standard_error_responses
from api.v1.views.serializer_utils import SanitizedCharField
from api.views.enums.type_filter import TypeFilter


class InputSerializer(serializers.Serializer):
    """
    Validates and sanitizes query parameters for the jobs list endpoint.
    """

    function = SanitizedCharField(required=False, default=None)
    provider = SanitizedCharField(required=False, default=None)
    status = SanitizedCharField(required=False, default=None)

    limit = serializers.IntegerField(
        required=False,
        default=settings.REST_FRAMEWORK["PAGE_SIZE"],
        min_value=0,
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    filter = serializers.ChoiceField(
        choices=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
        required=False,
        default=None,
    )
    created_after = serializers.DateTimeField(required=False, default=None)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobsListInputSerializer"

    def create(self, validated_data: dict):
        return JobFilters(**validated_data)


class ProgramSummarySerializer(serializers.ModelSerializer):
    """
    Summary fields for the related program.
    """

    class Meta:
        model = Program
        fields = ["id", "title", "provider"]
        ref_name = "JobsListProgramSummaryInputSerializer"


class JobSerializerWithoutResult(serializers.ModelSerializer):
    """
    Minimal job representation for listings.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "status", "program", "created", "sub_status"]
        ref_name = "JobsListWithoutResultInputSerializer"


def serialize_output(
    jobs: list[Job],
    total_count: int,
    request: Request,
    limit: int | None = None,
    offset: int | None = None,
) -> PaginatedResponse:
    """
    Build a paginated response with serialized jobs.

    Args:
        jobs: List of job instances.
        total_count: Total number of jobs matching the filters.
        request: The HTTP request (used to build pagination links).
        limit: Page size used for pagination.
        offset: Offset used for pagination.

    Returns:
        A dictionary with pagination metadata and serialized items.
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
        status.HTTP_200_OK: JobSerializerWithoutResult(many=True),
        **standard_error_responses(
            not_found_example="Qiskit Function XXX doesn't exist.",
        ),
    },
)
@endpoint("jobs", name="jobs-list")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_jobs(request: Request) -> Response:
    """
    List jobs for the authenticated user with optional filtering.

    Query params:
        - provider: Provider name.
        - function: Function title.
        - limit: Page size.
        - offset: Items to skip.
        - filter: 'catalog' | 'serverless'.
        - status: Job status.
        - created_after: ISO 8601 datetime cutoff.

    Returns:
        A paginated list of jobs matching the filters.
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    filters = cast(JobFilters, serializer.create(serializer.validated_data))
    user = cast(AbstractUser, request.user)

    jobs, total = JobsListUseCase().execute(user=user, filters=filters)
    return Response(serialize_output(jobs, total, request, filters.limit, filters.offset))
