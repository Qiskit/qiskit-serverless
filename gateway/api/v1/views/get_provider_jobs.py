"""
API V1: list jobs endpoint
"""
from typing import List, Optional
from urllib.parse import urlencode

from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes

from django.conf import settings
from api.models import Job
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

    limit = int(request.query_params.get("limit", settings.REST_FRAMEWORK["PAGE_SIZE"]))
    if limit < 0:
        raise ValueError("Limit must be non-negative")

    offset = int(request.query_params.get("offset", 0))
    if offset < 0:
        raise ValueError("Offset must be non-negative")

    provider = request.query_params.get("provider")
    function = request.query_params.get("function")
    if not provider or not function:
        raise ValueError("Qiskit Function title and Provider name are mandatory")

    return {
        "user": user,
        "limit": limit,
        "offset": offset,
        "provider": provider,
        "function": function,
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
    response_data = {
        "count": total_count,
        "next": None,
        "previous": None,
        "results": serializer.data,
    }

    if limit is None:
        return response_data

    offset = offset or 0
    base_url = request.build_absolute_uri(request.path)

    # Calculate next URL
    if offset + limit < total_count:
        next_params = {"limit": limit, "offset": offset + limit}
        response_data["next"] = f"{base_url}?{urlencode(next_params)}"

    # Calculate previous URL
    if offset > 0:
        prev_params = {"limit": limit, "offset": max(0, offset - limit)}
        response_data["previous"] = f"{base_url}?{urlencode(prev_params)}"

    return response_data


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
                    "error": openapi.Schema(
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
    It returns a list with the jobs for the provider function:
        provider_name/function_title

    Query parameters:
    - limit: Number of results to return per page
    - offset: Number of results to skip
    - provider: provider name
    - function: function title
    """
    try:
        input_data = serialize_input(request)
    except ValueError as e:
        return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    try:
        jobs, total = GetProviderJobsUseCase(
            user=input_data["user"],
            limit=input_data["limit"],
            offset=input_data["offset"],
            provider=input_data["provider"],
            function=input_data["function"],
        ).execute()
    except ProviderNotFoundException:
        return Response(
            {"message": f"Provider {input_data['provider']} doesn't exist."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except FunctionNotFoundException:
        return Response(
            {
                "message": f"Qiskit Function \
                    {input_data['provider']}/{input_data['function']} doesn't exist."
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        serialize_output(
            jobs, total, request, input_data["limit"], input_data["offset"]
        )
    )
