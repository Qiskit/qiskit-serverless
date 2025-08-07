"""
API V1: list jobs endpoint
"""
from typing import List, Optional

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes

from django.conf import settings
from django.utils.dateparse import parse_datetime
from api.models import Job
from api.v1.views.utils import create_paginated_response, parse_positive_int
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.use_cases.get_provider_jobs import (
    GetProviderJobsUseCase,
    ProviderNotFoundException,
    FunctionNotFoundException,
)


def serialize_input(request):
    """
    Prepare the input for the end-point with validation
    """
    user = request.user

    limit = parse_positive_int(
        request.query_params.get("limit"), settings.REST_FRAMEWORK["PAGE_SIZE"]
    )
    offset = parse_positive_int(request.query_params.get("offset"), 0)

    status_filter = request.query_params.get("status")

    created_after = None
    created_after_param = request.query_params.get("created_after")
    if created_after_param:
        created_after = parse_datetime(created_after_param)
        if created_after is None:
            raise ValueError(
                "Invalid created_after format. Use ISO 8601 format (e.g., '2024-01-01T00:00:00Z')"
            )

    provider = request.query_params.get("provider")
    function_name = request.query_params.get("function")
    if not provider or not function_name:
        raise ValueError("Qiskit Function title and Provider name are mandatory")

    return {
        "user": user,
        "limit": limit,
        "offset": offset,
        "status": status_filter,
        "created_after": created_after,
        "provider": provider,
        "function_name": function_name,
    }


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
    operation_description="List provider Jobs",
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
            type=openapi.TYPE_INTEGER,  # pylint: disable=duplicate-code
            minimum=0,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="Function Provider name",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "function",
            openapi.IN_QUERY,
            description="Function title",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@endpoint("jobs/provider")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_provider_jobs(request):
    """
    Return a list of jobs for a given provider/function.

    Query parameters:
    - limit: results per page
    - offset: results to skip
    - provider: provider name (required)
    - function: function title (required)
    """
    try:
        input_data = serialize_input(request)
    except ValueError as e:
        return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    try:
        jobs, total = GetProviderJobsUseCase(**input_data).execute()
    except ProviderNotFoundException:
        return Response(
            {"message": f"Provider {input_data['provider']} doesn't exist."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except FunctionNotFoundException:
        return Response(
            {
                "message": f"Qiskit Function {input_data['provider']}/{input_data['function_name']} doesn't exist."  # pylint: disable=line-too-long
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        serialize_output(
            jobs, total, request, input_data["limit"], input_data["offset"]
        )
    )
