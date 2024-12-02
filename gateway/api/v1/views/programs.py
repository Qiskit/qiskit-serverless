"""
Programs view api for V1.
"""

from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action

from api import views
from api.v1 import serializers as v1_serializers


class ProgramViewSet(views.ProgramViewSet):
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    serializer_class = v1_serializers.ProgramSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_serializer_job_config(*args, **kwargs):
        return v1_serializers.JobConfigSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_upload_program(*args, **kwargs):
        return v1_serializers.UploadProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_program(*args, **kwargs):
        return v1_serializers.RunProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_job(*args, **kwargs):
        return v1_serializers.RunJobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        return v1_serializers.JobSerializer(*args, **kwargs)

    @swagger_auto_schema(
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
    def list(self, request):
        return super().list(request)

    @swagger_auto_schema(
        operation_description="Upload a Qiskit Function",
        request_body=v1_serializers.UploadProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.UploadProgramSerializer},
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        return super().upload(request)

    @swagger_auto_schema(
        operation_description="Run an existing Qiskit Function",
        request_body=v1_serializers.RunProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
    )
    @action(methods=["POST"], detail=False)
    def run(self, request):
        return super().run(request)

    @swagger_auto_schema(
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
        responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="get_by_title/(?P<title>[^/.]+)")
    def get_by_title(self, request, title):
        return super().get_by_title(request, title)
