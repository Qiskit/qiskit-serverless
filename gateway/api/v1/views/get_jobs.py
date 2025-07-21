"""
API V1: list jobs endpoint
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view

from typing import List
from api.models import Job
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.serializers import JobSerializerWithoutResult
from api.use_cases.get_jobs import (
    GetJobsUseCase,
)


def serialize_input(request):
    """
    Prepare the input for the end-point
    """
    user = request.user
    limit = request.query_params.get(
        "limit", 50
    )  # TODO check what was the previous default limit
    offset = request.query_params.get("offset", 0)
    input_filter = request.query_params.get("filter")

    return {"user": user, "limit": limit, "offset": offset, "filter": input_filter}


def serialize_output(jobs: List[Job]):
    """
    Prepare the output for the end-point
    """
    page = self.paginate_queryset(jobs)
    if page is not None:
        serializer = JobSerializerWithoutResult(page, many=True)
        return self.get_paginated_response(serializer.data)

    serializer = JobSerializerWithoutResult(jobs, many=True)

    return Response(serializer.data)


@swagger_auto_schema(
    operation_description="List author Jobs",
    responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=True)},
)
@endpoint("jobs")
@api_view(["GET"])
def get_jobs(request):
    """
    List jobs
    """
    input_data = serialize_input(request)

    result = GetJobsUseCase(
        user=input_data["user"],
        limit=input_data["limit"],
        offset=input_data["offset"],
        filter_type=input_data["filter"],
    ).execute()

    return serialize_output(result)
