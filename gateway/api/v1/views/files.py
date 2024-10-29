"""
Files view api for V1.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions
from rest_framework.decorators import action

from api.permissions import IsOwner
from api import views


class FilesViewSet(views.FilesViewSet):
    """
    Files view set.
    """

    permission_classes = [permissions.IsAuthenticated, IsOwner]

    @swagger_auto_schema(
        operation_description="List of available files in the user directory",
        manual_parameters=[
            openapi.Parameter(
                "provider",
                openapi.IN_QUERY,
                description="provider name",
                type=openapi.TYPE_STRING,
                required=False,
            ),
            openapi.Parameter(
                "function",
                openapi.IN_QUERY,
                description="function title",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
    )
    def list(self, request):
        return super().list(request)

    @swagger_auto_schema(
        operation_description="List of available files in the provider directory",
        manual_parameters=[
            openapi.Parameter(
                "provider",
                openapi.IN_QUERY,
                description="provider name",
                type=openapi.TYPE_STRING,
                required=True,
            ),
            openapi.Parameter(
                "function",
                openapi.IN_QUERY,
                description="function title",
                type=openapi.TYPE_STRING,
                required=True,
            ),
        ],
    )
    @action(methods=["GET"], detail=False, url_path="provider")
    def provider_list(self, request):
        return super().provider_list(request)

    @swagger_auto_schema(
        operation_description="Download a specific file",
        manual_parameters=[
            openapi.Parameter(
                "file",
                openapi.IN_QUERY,
                description="file name",
                type=openapi.TYPE_STRING,
                required=True,
            ),
            openapi.Parameter(
                "provider",
                openapi.IN_QUERY,
                description="provider name",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
    )
    @action(methods=["GET"], detail=False)
    def download(self, request):
        return super().download(request)

    @swagger_auto_schema(
        operation_description="Deletes file uploaded or produced by the programs",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "file": openapi.Schema(
                    type=openapi.TYPE_STRING, description="file name"
                ),
                "provider": openapi.Schema(
                    type=openapi.TYPE_STRING, description="provider name"
                ),
            },
            required=["file"],
        ),
    )
    @action(methods=["DELETE"], detail=False)
    def delete(self, request):
        return super().delete(request)

    @swagger_auto_schema(
        operation_description="Upload selected file",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "file": openapi.Schema(type=openapi.TYPE_FILE, description="file name"),
                "provider": openapi.Schema(
                    type=openapi.TYPE_STRING, description="provider name"
                ),
            },
            required=["file"],
        ),
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        return super().upload(request)
