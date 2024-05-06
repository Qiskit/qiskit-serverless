"""
Views api for V1.
"""

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action


from api import views
from api.models import Job, RuntimeJob
from api.permissions import IsOwner
from . import serializers as v1_serializers


class ProgramViewSet(views.ProgramViewSet):  # pylint: disable=too-many-ancestors
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    serializer_class = v1_serializers.ProgramSerializer
    lookup_field = "title"
    pagination_class = None
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_serializer_job_config(*args, **kwargs):
        return v1_serializers.JobConfigSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_upload_program(*args, **kwargs):
        return v1_serializers.UploadProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_existing_program(*args, **kwargs):
        return v1_serializers.RunExistingProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_job(*args, **kwargs):
        return v1_serializers.RunJobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_program(*args, **kwargs):
        return v1_serializers.RunProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_model_serializer_run_program(*args, **kwargs):
        return v1_serializers.RunProgramModelSerializer(*args, **kwargs)

    @swagger_auto_schema(
        operation_description="Get a specific Qiskit Patterns",
        responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer(many=False)},
    )
    def retrieve(self, request, title=None):
        return super().retrieve(request, title)

    @swagger_auto_schema(
        operation_description="List author Qiskit Patterns",
        responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer(many=True)},
    )
    def list(self, request):
        return super().list(request)

    @swagger_auto_schema(
        operation_description="Upload a Qiskit Pattern",
        request_body=v1_serializers.UploadProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.UploadProgramSerializer},
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        return super().upload(request)

    @swagger_auto_schema(
        operation_description="Run an existing Qiskit Pattern",
        request_body=v1_serializers.RunExistingProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
    )
    @action(methods=["POST"], detail=False)
    def run_existing(self, request):
        return super().run_existing(request)

    @swagger_auto_schema(
        operation_description="Run and upload a Qiskit Pattern",
        request_body=v1_serializers.RunProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
    )
    @action(methods=["POST"], detail=False)
    def run(self, request):
        return super().run(request)


class JobViewSet(views.JobViewSet):  # pylint: disable=too-many-ancestors
    """
    Job view set first version. Use JobSerializer V1.
    """

    queryset = Job.objects.all()
    serializer_class = v1_serializers.JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer


class FilesViewSet(views.FilesViewSet):
    """
    Files view set.
    """

    permission_classes = [permissions.IsAuthenticated, IsOwner]


class RuntimeJobViewSet(views.RuntimeJobViewSet):  # pylint: disable=too-many-ancestors
    """
    RuntimeJob view set first version. Use RuntomeJobSerializer V1.
    """

    serializer_class = v1_serializers.RuntimeJobSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.RuntimeJobSerializer

    def get_queryset(self):
        # Allow unauthenticated users to read the swagger documentation
        if self.request.user is None or not self.request.user.is_authenticated:
            return RuntimeJob.objects.none()
        return RuntimeJob.objects.all().filter(job__author=self.request.user)
