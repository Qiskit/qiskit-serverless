"""
API V1: list jobs endpoint
"""
# pylint: disable=duplicate-code, disable=abstract-method
from typing import cast, List, Optional

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.models import Job, Program
from api.repositories.jobs import JobFilters
from api.use_cases.jobs.provider_list import JobsProviderListUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.utils import create_paginated_response
from api.v1.views.swagger_utils import standard_error_responses
from api.v1.views.serializer_utils import SanitizedCharField
from api.views.enums.type_filter import TypeFilter


class TypeFilterField(serializers.ChoiceField):
    """ChoiceField that returns a TypeFilter enum (or None)."""

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        return TypeFilter(value) if value else None


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = SanitizedCharField(required=False, default=None)
    provider = SanitizedCharField(
        required=True,
        error_messages={"required": "'provider' not provided or is not valid"},
    )
    limit = serializers.IntegerField(
        required=False, default=settings.REST_FRAMEWORK["PAGE_SIZE"], min_value=0
    )
    offset = serializers.IntegerField(required=False, default=0, min_value=0)
    filter = TypeFilterField(
        choices=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
        required=False,
        default=None,
    )
    status = SanitizedCharField(required=False, default=None)
    created_after = serializers.DateTimeField(required=False, default=None)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobsProviderListInputSerializer"

    def create(self, validated_data: dict):
        return JobFilters(**validated_data)


class ProgramSummarySerializer(serializers.ModelSerializer):
    """
    Program serializer with summary fields for job listings.
    """

    class Meta:
        model = Program
        fields = ["id", "title", "provider"]
        ref_name = "JobsProviderListProgramSummaryInputSerializer"


class JobSerializerWithoutResult(serializers.ModelSerializer):
    """
    Job serializer. Include basic fields from the initial model.
    """

    program = ProgramSummarySerializer(many=False)

    class Meta:
        """Meta class to define input serializer name"""

        model = Job
        fields = ["id", "status", "program", "created", "sub_status"]
        ref_name = "JobsProviderListWithoutResultInputSerializer"


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
    operation_description="List provider jobs. Use filters via query params.",
    manual_parameters=[
        openapi.Parameter(
            name="provider",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=True,
            description="Provider name (required).",
        ),
        openapi.Parameter(
            name="function",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Function title.",
        ),
        openapi.Parameter(
            name="limit",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=False,
            default=settings.REST_FRAMEWORK["PAGE_SIZE"],
            description="Results per page.",
        ),
        openapi.Parameter(
            name="offset",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_INTEGER,
            required=False,
            default=0,
            description="Number of results to skip.",
        ),
        openapi.Parameter(
            name="filter",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            enum=[TypeFilter.CATALOG, TypeFilter.SERVERLESS],
            required=False,
            description="Filter by job type: 'catalog' or 'serverless'.",
        ),
        openapi.Parameter(
            name="status",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="Filter by job status.",
        ),
        openapi.Parameter(
            name="created_after",
            in_=openapi.IN_QUERY,
            type=openapi.TYPE_STRING,
            required=False,
            description="ISO 8601 datetime; only jobs created after this.",
        ),
    ],
    responses={
        status.HTTP_200_OK: JobSerializerWithoutResult(many=True),
        **standard_error_responses(
            not_found_example="Provider XXX doesn't exist.",
        ),
    },
)
@endpoint("jobs/provider", name="jobs-provider-list")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_provider_jobs(request: Request) -> Response:
    """
    Return a list of jobs for the given provider (and optional filters).
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    filters = JobFilters(**serializer.validated_data)
    user = cast(AbstractUser, request.user)

    jobs, total = JobsProviderListUseCase().execute(user=user, filters=filters)
    return Response(
        serialize_output(jobs, total, request, filters.limit, filters.offset)
    )
