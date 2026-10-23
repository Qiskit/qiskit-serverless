"""
API endpoint for reading a job status with a job status token.
"""

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.services.authentication.job_status_token import JOB_STATUS_TOKEN_HEADER, JobStatusTokenBackend
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.models import Job

logger = logging.getLogger("api.api.v1.views.jobs.status")


@swagger_auto_schema(
    method="get",
    operation_description=(
        "Read the status of a job with the job status token that `GET /jobs/{id}/` returns in the "
        f"`{JOB_STATUS_TOKEN_HEADER}` header. It does not accept the API key."
    ),
    manual_parameters=[
        openapi.Parameter(name=JOB_STATUS_TOKEN_HEADER, in_=openapi.IN_HEADER, type=openapi.TYPE_STRING, required=True),
    ],
    security=[],
    responses={
        status.HTTP_200_OK: openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "status": openapi.Schema(type=openapi.TYPE_STRING),
                "sub_status": openapi.Schema(type=openapi.TYPE_STRING, x_nullable=True),
                "fleet_id": openapi.Schema(type=openapi.TYPE_STRING, x_nullable=True),
            },
        ),
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/status", method="GET", name="jobs-status")
@authentication_classes([JobStatusTokenBackend])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def job_status(request: Request, job_id: UUID) -> Response:
    """Return the status, sub-status and fleet id of the job the token was issued for."""
    user = cast(AbstractUser, request.user)
    if request.auth != str(job_id):
        raise JobNotFoundException(str(job_id))
    job = Job.objects.filter(id=job_id, author_id=user.id).values("status", "sub_status", "fleet_id").first()
    if job is None:
        raise JobNotFoundException(str(job_id))

    logger.debug("[jobs-status] user_id=%s job_id=%s status=%s", user.id, job_id, job["status"])
    return Response(job, headers={"Cache-Control": "no-store"})
