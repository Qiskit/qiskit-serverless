"""
API V1: list jobs endpoint
"""

from typing import List, Optional
from urllib.parse import urlencode

from drf_yasg.utils import swagger_auto_schema
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes

from django.conf import settings
from api.models import Job
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.use_cases.get_jobs import (
    GetJobsUseCase,
)


def serialize_input(request):
    """
    Prepare the input for the end-point
    """
    user = request.user
    limit = request.query_params.get("limit", settings.REST_FRAMEWORK["PAGE_SIZE"])
    offset = request.query_params.get("offset", 0)
    input_filter = request.query_params.get("filter")

    return {"user": user, "limit": limit, "offset": offset, "filter": input_filter}


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
    operation_description="List author Jobs",
    responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=True)},
)
@endpoint("jobs")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_jobs(request):
    """
    List jobs
    """
    input_data = serialize_input(request)

    jobs, total = GetJobsUseCase(
        user=input_data["user"],
        limit=input_data["limit"],
        offset=input_data["offset"],
        filter_type=input_data["filter"],
    ).execute()

    return Response(
        serialize_output(
            jobs, total, request, input_data["limit"], input_data["offset"]
        )
    )
