"""
Views api for V1.
"""

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination


from api import views
from api.permissions import IsOwner
from . import serializers as v1_serializers


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

    @swagger_auto_schema(
        operation_description="List author Qiskit Functions",
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


class JobViewSet(views.JobViewSet):
    """
    Job view set first version. Use JobSerializer V1.
    """

    serializer_class = v1_serializers.JobSerializer
    pagination_class = LimitOffsetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer

    @swagger_auto_schema(
        operation_description="Get author Job",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=False)},
    )
    def retrieve(self, request, pk=None):
        return super().retrieve(request, pk)

    @swagger_auto_schema(
        operation_description="List author Jobs",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=True)},
    )
    def list(self, request):
        return super().list(request)

    @swagger_auto_schema(
        operation_description="Save the result of a job",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=False)},
    )
    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):
        return super().result(request, pk)

    ### We are not returning serializers in the rest of the end-points


class FilesViewSet(views.FilesViewSet):
    """
    Files view set.
    """

    permission_classes = [permissions.IsAuthenticated, IsOwner]


class CatalogViewSet(views.CatalogViewSet):
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    serializer_class = v1_serializers.ListCatalogSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
