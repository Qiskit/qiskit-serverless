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
        operation_description="Upload selected file",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "file": openapi.Schema(
                    type=openapi.TYPE_FILE, description="File to be uploaded"
                )
            },
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
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        return super().upload(request)

    @swagger_auto_schema(
        operation_description="Upload a file into the provider directory",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "file": openapi.Schema(
                    type=openapi.TYPE_FILE, description="File to be uploaded"
                )
            },
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
                required=True,
            ),
        ],
    )
    @action(methods=["POST"], detail=False, url_path="provider/upload")
    def provider_upload(self, request):
        return super().provider_upload(request)
