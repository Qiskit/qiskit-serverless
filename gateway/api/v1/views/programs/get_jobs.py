"""API endpoint for listing jobs of a Qiskit Function (deprecated)."""

import logging
import uuid
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.get_jobs import GetJobsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, Program

logger = logging.getLogger("api.api.v1.views.programs.get_jobs")


class ProgramSerializer(serializers.ModelSerializer):
    """Nested program representation for job list responses."""

    provider = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Program
        fields = [
            "id",
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "provider",
            "description",
            "documentation_url",
            "type",
            "version",
            "runner",
        ]


class OutputSerializer(serializers.ModelSerializer):
    """Job representation for program job list responses."""

    program = ProgramSerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "result", "status", "program", "created", "sub_status", "fleet_id", "compute_profile"]
        ref_name = "ProgramsGetJobsOutput"


class OutputSerializerWithoutResult(serializers.ModelSerializer):
    """Job representation for cross-author provider listings.

    A provider admin may list every author's jobs for the function, but the `result`
    field is author-private everywhere else, so it is never serialized here.
    """

    program = ProgramSerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "status", "program", "created", "sub_status", "fleet_id", "compute_profile"]
        ref_name = "ProgramsGetJobsOutputWithoutResult"


@swagger_auto_schema(
    method="get",
    operation_description="[Deprecated] List jobs for a Qiskit Function",
    responses={
        status.HTTP_200_OK: OutputSerializer(many=True),
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

    jobs, is_provider_listing = GetJobsUseCase().execute(user, accessible_functions, pk)
    logger.info("[programs-get-jobs] user_id=%s program_id=%s | Jobs listed ok", user.id, pk)
    if is_provider_listing:
        return Response(OutputSerializerWithoutResult(jobs, many=True).data)
    return Response(OutputSerializer(jobs, many=True).data)
