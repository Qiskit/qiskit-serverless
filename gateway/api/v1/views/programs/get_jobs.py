"""API endpoint for listing jobs of a Qiskit Function (deprecated)."""

import logging
import uuid
from typing import cast

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.access_policies.providers import ProviderAccessPolicy
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job
from core.models import Program as Function

logger = logging.getLogger("api.api.v1.views.programs.get_jobs")


@swagger_auto_schema(
    method="get",
    operation_description="[Deprecated] List jobs for a Qiskit Function",
    responses={
        status.HTTP_200_OK: v1_serializers.JobSerializer(many=True),
        **standard_error_responses(not_found_example="program [xxx] was not found."),
    },
)
@endpoint("programs/<uuid:pk>/get_jobs", method="GET", name="programs-get-jobs")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_jobs(request: Request, pk: uuid.UUID) -> Response:
    """Return jobs for a program."""
    program = Function.objects.filter(id=pk).first()
    if not program:
        return Response(
            {"message": f"program [{pk}] was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-get-jobs] user_id=%s program_id=%s program=%s accessible_functions=%s",
        request.user.id,
        pk,
        program.title,
        accessible_functions,
    )

    user_is_provider = False
    if program.provider:
        user_is_provider = ProviderAccessPolicy.can_list_jobs(
            user=request.user,
            provider=program.provider,
            function_title=program.title,
            accessible_functions=accessible_functions,
        )

    jobs = (
        Job.objects.filter(program=program)
        if user_is_provider
        else Job.objects.filter(program=program, author=request.user)
    )

    logger.info(
        "[programs-get-jobs] user_id=%s program_id=%s program=%s | Jobs listed ok",
        request.user.id,
        pk,
        program.title,
    )
    return Response(v1_serializers.JobSerializer(jobs, many=True).data)
