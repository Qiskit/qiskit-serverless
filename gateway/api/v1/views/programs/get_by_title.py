"""API endpoint for retrieving a Qiskit Function by title."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.get_by_title import GetFunctionByTitleUseCase
from api.utils import sanitize_name
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.get_by_title")


def _parse_title_and_provider(title: str, provider: str | None) -> tuple[str, str | None]:
    """Split 'provider/title' convention or sanitize inputs."""
    if provider:
        return sanitize_name(title), sanitize_name(provider)
    parts = title.split("/")
    if len(parts) == 1:
        return sanitize_name(title), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve a Qiskit Function using the title",
    manual_parameters=[
        openapi.Parameter(
            "title",
            openapi.IN_PATH,
            description="The title of the function",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="The provider in case the function is owned by a provider",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={
        status.HTTP_200_OK: v1_serializers.ProgramSerializer,
        **standard_error_responses(not_found_example="Qiskit Function [XXX] doesn't exist."),
    },
)
@endpoint("programs/get_by_title/<str:title>", method="GET", name="programs-get-by-title")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_by_title(request: Request, title: str) -> Response:
    """Retrieve a single Qiskit Function by title."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    function_title, provider_name = _parse_title_and_provider(title, request.query_params.get("provider"))
    logger.info(
        "[programs-get-by-title] user_id=%s program=%s provider=%s accessible_functions=%s",
        user.id,
        function_title,
        provider_name,
        accessible_functions,
    )

    function = GetFunctionByTitleUseCase().execute(user, accessible_functions, function_title, provider_name)
    logger.info(
        "[programs-get-by-title] user_id=%s program=%s provider=%s | Function retrieved ok",
        user.id,
        function_title,
        provider_name,
    )
    return Response(v1_serializers.ProgramSerializer(function).data)
