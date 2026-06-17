"""
API endpoint to retrieve runtime jobs associated with a job.
"""

import logging
from typing import Any, cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api import serializers as api_serializers
from api.use_cases.jobs.get_runtime_jobs import GetRuntimeJobsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses

logger = logging.getLogger("api.api.v1.views.jobs.get_runtime_jobs")


class RuntimeJobSerializer(api_serializers.RuntimeJobSerializer):
    """Runtime job serializer fields."""

    class Meta(api_serializers.RuntimeJobSerializer.Meta):
        fields = ["runtime_job", "runtime_session"]


def serialize_output(out_runtime_jobs: Any) -> dict[str, Any]:
    """Build the response payload with serialized runtime jobs."""
    return {"runtime_jobs": RuntimeJobSerializer(out_runtime_jobs, many=True).data}


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve runtime jobs associated with a job.",
    responses={
        status.HTTP_200_OK: RuntimeJobSerializer,
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
            unauthorized_example="Authentication credentials were not provided or are invalid.",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/runtime_jobs", method="GET", name="jobs-runtime-jobs")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_runtime_jobs(request: Request, job_id: UUID) -> Response:
    """Retrieve runtime jobs for a job."""
    user = cast(AbstractUser, request.user)
    out_runtime_jobs = GetRuntimeJobsUseCase().execute(job_id, user)
    logger.info("[jobs-runtime-jobs:get] user_id=%s job_id=%s | Runtime jobs retrieved ok", user.id, job_id)
    return Response(serialize_output(out_runtime_jobs))
