"""API endpoint for listing jobs of a Qiskit Function (deprecated)."""

import logging
import uuid
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.get_jobs import GetJobsUseCase
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.get_jobs")


@swagger_auto_schema(
    method="get",
    operation_description="[Deprecated] List jobs for a Qiskit Function",
    responses={
        status.HTTP_200_OK: v1_serializers.JobSerializer(many=True),
        **standard_error_responses(not_found_example="Qiskit Function [xxx] doesn't exist."),
    },
)
@endpoint("programs/<uuid:pk>/get_jobs", method="GET", name="programs-get-jobs")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_jobs(request: Request, pk: uuid.UUID) -> Response:
    """Return jobs for a program."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-get-jobs] user_id=%s program_id=%s accessible_functions=%s",
        user.id,
        pk,
        accessible_functions,
    )

    jobs = GetJobsUseCase().execute(user, accessible_functions, pk)
    logger.info("[programs-get-jobs] user_id=%s program_id=%s | Jobs listed ok", user.id, pk)
    return Response(v1_serializers.JobSerializer(jobs, many=True).data)
