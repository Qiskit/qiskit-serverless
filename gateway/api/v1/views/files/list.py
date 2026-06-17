"""
API V1: List files end-point.
"""

# pylint: disable=duplicate-code
import logging
from typing import cast
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.models import AbstractUser
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework import serializers


from api.use_cases.files.list import FilesListUseCase
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_name
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.files.list")

# pylint: disable=abstract-method


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=True)
    provider = serializers.CharField(required=False, default=None)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "FilesListInputSerializer"

    def validate_function(self, value: str):
        """
        Validates the function title
        """
        return sanitize_name(value)

    def validate_provider(self, value: str):
        """
        Validates the proivider name
        """
        return sanitize_name(value)


@swagger_auto_schema(
    method="get",
    operation_description="List of available files in the user directory",
    manual_parameters=[
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="the provider name",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "function",
            openapi.IN_QUERY,
            description="the function title",
            type=openapi.TYPE_STRING,
            required=True,
        ),
    ],
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="List of files",
            schema=openapi.Schema(type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_STRING)),
            examples={
                "application/json": [
                    "file",
                ]
            },
        ),
        status.HTTP_401_UNAUTHORIZED: openapi.Response(
            description="Authentication credentials were not provided or are invalid."
        ),
    },
)
@endpoint("files", method="GET")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def files_list(request: Request) -> Response:
    """
    List user files end-point
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    function = serializer.validated_data.get("function")
    provider = serializer.validated_data.get("provider")

    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[files-list] user_id=%s function=%s provider=%s accessible_functions=%s",
        user.id,
        function,
        provider,
        accessible_functions,
    )

    files = FilesListUseCase().execute(user, provider, function, accessible_functions=accessible_functions)
    logger.info("[files-list] user_id=%s function=%s provider=%s | Files listed ok", user.id, function, provider)
    return Response({"results": files})
