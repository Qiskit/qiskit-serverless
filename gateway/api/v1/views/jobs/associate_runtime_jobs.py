"""
API endpoint to associate a runtime job with a job.
"""

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.jobs.associate_runtime_jobs import AssociateRuntimeJobsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses

logger = logging.getLogger("api.api.v1.views.jobs.associate_runtime_jobs")


class InputSerializer(serializers.Serializer):
    """Validates the request body for associating runtime jobs to a serverless job."""

    runtime_job = serializers.CharField(required=True)
    runtime_session = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        ref_name = "RuntimeJobsInputSerializer"


@swagger_auto_schema(
    method="post",
    operation_description="Associate a runtime job with a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: serializers.Serializer(),
        **standard_error_responses(
            bad_request_example="Got empty `runtime_job` field. Please, specify `runtime_job`.",
            not_found_example="Job [XXXX] not found",
            unauthorized_example="Authentication credentials were not provided or are invalid.",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/runtime_jobs", method="POST", name="jobs-runtime-jobs")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def associate_runtime_jobs(request: Request, job_id: UUID) -> Response:
    """Associate a new runtime job with a job."""
    user = cast(AbstractUser, request.user)
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    runtime_job = serializer.validated_data.get("runtime_job")
    runtime_session = serializer.validated_data.get("runtime_session")
    message = AssociateRuntimeJobsUseCase().execute(job_id, runtime_job, runtime_session, user)
    logger.info(
        "[jobs-runtime-jobs:post] user_id=%s job_id=%s runtime_job=%s | Runtime job linked ok",
        user.id,
        job_id,
        runtime_job,
    )
    return Response({"message": message})
