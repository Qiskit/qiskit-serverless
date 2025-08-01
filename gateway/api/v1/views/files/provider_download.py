"""
API V1: Download provider file end-point.
"""
# pylint: disable=duplicate-code
from typing import cast
from django.http import StreamingHttpResponse
from django.contrib.auth.models import AbstractBaseUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework import serializers

from api.use_cases.files.provider_download import FilesProviderDownloadUseCase
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_file_name, sanitize_name

# pylint: disable=abstract-method
class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=True)
    provider = serializers.CharField(required=True)
    file = serializers.CharField(required=True)

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

    def validate_file(self, value: str):
        """
        Validates the file name
        """
        return sanitize_file_name(value)


@swagger_auto_schema(
    method="get",
    operation_description="Download a specific file in the provider directory",
    manual_parameters=[
        openapi.Parameter(
            "file",
            openapi.IN_QUERY,
            description="File name",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "function",
            openapi.IN_QUERY,
            description="Qiskit Function title",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="Provider name",
            type=openapi.TYPE_STRING,
            required=True,
        ),
    ],
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="Requested file",
            content_type="application/octet-stream",
            schema=openapi.Schema(type=openapi.TYPE_FILE),
            examples={
                "application/octet-stream": {
                    "summary": "Example file",
                    "value": "Example file content",  # o un texto base64 corto si prefieres
                }
            },
        ),
        status.HTTP_404_NOT_FOUND: openapi.Response(
            description="File not found.",
        ),
        status.HTTP_401_UNAUTHORIZED: openapi.Response(
            description="Authentication credentials were not provided or are invalid."
        ),
    },
)
@endpoint("files/provider/download", name="files-provider-download")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def files_provider_download(request: Request) -> Response:
    """
    Download a file from the provider storage
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    function = serializer.validated_data.get("function")
    provider = serializer.validated_data.get("provider")
    file = serializer.validated_data.get("file")

    user = cast(AbstractBaseUser, request.user)

    result = FilesProviderDownloadUseCase().execute(user, provider, function, file)

    file_wrapper, file_type, file_size = result
    response = StreamingHttpResponse(file_wrapper, content_type=file_type)
    response["Content-Length"] = file_size
    response["Content-Disposition"] = f"attachment; filename={file}"
    return response
