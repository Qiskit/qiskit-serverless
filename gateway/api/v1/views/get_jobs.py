"""
API V1: list jobs endpoint
"""

# pylint: disable=duplicate-code
from typing import List, Optional

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.utils.dateparse import parse_datetime

from django.conf import settings
from api.models import Job
from api.v1.views.utils import create_paginated_response, parse_positive_int
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.views.enums.type_filter import TypeFilter
from api.use_cases.get_jobs import GetJobsUseCase


def serialize_input(request):
    """Parse and validate query parameters from the request."""
    user = request.user

    limit = parse_positive_int(
        request.query_params.get("limit"), settings.REST_FRAMEWORK["PAGE_SIZE"]
    )
    offset = parse_positive_int(request.query_params.get("offset"), 0)

    type_filter = None
    type_param = request.query_params.get("filter")
    if type_param:
        try:
            type_filter = TypeFilter(type_param)
        except ValueError as exc:
            raise ValueError(
                f"Invalid type filter. Must be one of: {', '.join([e.value for e in TypeFilter])}"
            ) from exc

    status_filter = request.query_params.get("status")

    created_after = None
    created_after_param = request.query_params.get("created_after")
    if created_after_param:
        created_after = parse_datetime(created_after_param)
        if created_after is None:
            raise ValueError(
                "Invalid created_after format. Use ISO 8601 format (e.g., '2024-01-01T00:00:00Z')"
            )

    function_name = request.query_params.get("function")

    return {
        "user": user,
        "limit": limit,
        "offset": offset,
        "type_filter": type_filter,
        "status": status_filter,
        "created_after": created_after,
        "function_name": function_name,
    }


def serialize_output(
    jobs: List[Job],
    total_count: int,
    request,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    """Serialize job list into a paginated API response."""
    serializer = v1_serializers.JobSerializerWithoutResult(jobs, many=True)
    return create_paginated_response(
        data=serializer.data,
        total_count=total_count,
        request=request,
        limit=limit,
        offset=offset,
    )


@swagger_auto_schema(
    method="get",
    operation_description="List author Jobs with filtering support",
    responses={
        status.HTTP_200_OK: v1_serializers.JobSerializerWithoutResult(many=True),
        status.HTTP_400_BAD_REQUEST: openapi.Response(
            description="Bad Request - Invalid parameters",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "message": openapi.Schema(
                        type=openapi.TYPE_STRING, description="Error message"
                    )
                },
            ),
        ),
    },
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return per page (max: 1000, default: from settings)",
            type=openapi.TYPE_INTEGER,
            minimum=0,
            default=settings.REST_FRAMEWORK["PAGE_SIZE"],
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Number of results to skip before starting to collect results",
            type=openapi.TYPE_INTEGER,
            minimum=0,
        ),
        openapi.Parameter(
            "filter",
            openapi.IN_QUERY,
            description="Filter by job type",
            type=openapi.TYPE_STRING,
            enum=[e.value for e in TypeFilter],
        ),
        openapi.Parameter(
            "status",
            openapi.IN_QUERY,
            description="Filter by job status",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "created_after",
            openapi.IN_QUERY,
            description="Filter jobs created after this datetime. Use ISO 8601"
            " format (e.g., '2024-01-01T00:00:00Z')",
            type=openapi.TYPE_STRING,
            format="date-time",
        ),
    ],
)
@endpoint("jobs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_jobs(request):
    """
    List jobs with optional filtering.

    Query parameters:
    - limit: Number of results to return per page
    - offset: Number of results to skip
    - type: Filter by job type ('catalog' or 'serverless')
    - status: Filter by job status
    - created_after: Filter jobs created after this datetime (ISO 8601 format)
    """
    try:
        input_data = serialize_input(request)
    except ValueError as e:
        return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    jobs, total = GetJobsUseCase(**input_data).execute()

    return Response(
        serialize_output(
            jobs, total, request, input_data["limit"], input_data["offset"]
        )
    )
