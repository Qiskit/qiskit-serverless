"""
API V1: Delete file end-point.
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

from api.use_cases.files.delete import FilesDeleteUseCase
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_file_name, sanitize_name

# pylint: disable=abstract-method


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    function = serializers.CharField(required=True)
    provider = serializers.CharField(required=False, default=None)
    file = serializers.CharField(required=True)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "FilesDeleteInputSerializer"

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
    method="delete",
    operation_description="Deletes file uploaded or produced by the programs",
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
            required=False,
        ),
    ],
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="The ok message",
            examples={"application/json": {"message": "Requested file was deleted."}},
        ),
        status.HTTP_404_NOT_FOUND: openapi.Response(
            description="File not found.",
        ),
        status.HTTP_401_UNAUTHORIZED: openapi.Response(
            description="Authentication credentials were not provided or are invalid."
        ),
    },
)
@endpoint("files/delete")
@api_view(["DELETE"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def files_delete(request: Request) -> Response:
    """
    Delete a file from the user storage
    """
    serializer = InputSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)

    function = serializer.validated_data.get("function")
    provider = serializer.validated_data.get("provider")
    file = serializer.validated_data.get("file")

    user = cast(AbstractUser, request.user)

    FilesDeleteUseCase().execute(user, provider, function, file)

    return Response(
        {"message": "Requested file was deleted."}, status=status.HTTP_200_OK
    )
