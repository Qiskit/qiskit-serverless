"""API endpoint for listing Qiskit Functions."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.list import ListFunctionsUseCase
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.list")


@swagger_auto_schema(
    method="get",
    operation_description="List author Qiskit Functions",
    manual_parameters=[
        openapi.Parameter(
            "filter",
            openapi.IN_QUERY,
            description="Filters that you can apply for list: serverless, catalog or empty",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer(many=True)},
)
@endpoint("programs", method="GET", name="programs-list")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def list_programs(request: Request) -> Response:
    """List Qiskit Functions accessible to the authenticated user."""
    type_filter = request.query_params.get("filter")
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-list] user_id=%s filter=%s accessible_functions=%s",
        user.id,
        type_filter,
        accessible_functions,
    )

    functions = ListFunctionsUseCase().execute(user, accessible_functions, type_filter)
    logger.info("[programs-list] user_id=%s filter=%s | Functions listed ok", user.id, type_filter)
    return Response(v1_serializers.ProgramSerializer(functions, many=True).data)
