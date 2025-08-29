"""
API V1: List provider files end-point.
"""
# pylint: disable=duplicate-code
from typing import cast
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from django.contrib.auth.models import AbstractUser
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework import serializers

from api.use_cases.files.provider_list import FilesProviderListUseCase
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_name

# pylint: disable=abstract-method
class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=True)
    provider = serializers.CharField(required=True)

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
    operation_description="List of available files in the provider directory",
    manual_parameters=[
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="the provider name",
            type=openapi.TYPE_STRING,
            required=True,
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
            schema=openapi.Schema(
                type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_STRING)
            ),
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
@endpoint("files/provider")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def files_provider_list(request: Request) -> Response:
    """
    List provider files end-point
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    function = serializer.validated_data.get("function")
    provider = serializer.validated_data.get("provider")

    user = cast(AbstractUser, request.user)

    files = FilesProviderListUseCase().execute(user, provider, function)

    return Response({"results": files})
