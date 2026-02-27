"""
API V1: Upload file end-point.
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

from api.use_cases.files.upload import FilesUploadUseCase
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_name
from api.v1.views.utils import validate_uploaded_file

# pylint: disable=abstract-method


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=True)
    provider = serializers.CharField(required=False, default=None)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "FilesUploadInputSerializer"

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
    method="post",
    operation_description="Upload selected file",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={"file": openapi.Schema(type=openapi.TYPE_FILE, description="File to be uploaded")},
        required=["file"],
    ),
    manual_parameters=[
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
            required=False,
        ),
    ],
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="The path to file",
            examples={"application/json": {"message": "path/to/file"}},
        ),
        status.HTTP_404_NOT_FOUND: openapi.Response(
            description="Function or provider does not exist",
        ),
        status.HTTP_401_UNAUTHORIZED: openapi.Response(
            description="Authentication credentials were not provided or are invalid."
        ),
    },
)
@endpoint("files/upload")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def files_upload(request: Request) -> Response:
    """
    Upload a file into the user storage.
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    function = serializer.validated_data.get("function")
    provider = serializer.validated_data.get("provider")

    uploaded_file = request.FILES.get("file")
    validate_uploaded_file(uploaded_file)

    user = cast(AbstractUser, request.user)

    result = FilesUploadUseCase().execute(user, provider, function, uploaded_file)

    return Response({"message": result})
