"""
Views api for V1.
"""

from rest_framework import permissions


from api import views
from api.models import Program, Job, RuntimeJob, CatalogEntry
from api.permissions import IsOwner, CatalogUpdate
from . import serializers as v1_serializers
from . import services as v1_services


class ProgramViewSet(views.ProgramViewSet):  # pylint: disable=too-many-ancestors
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    queryset = Program.objects.all()
    serializer_class = v1_serializers.ProgramSerializer
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_service_program_class():
        return v1_services.ProgramService

    @staticmethod
    def get_service_job_config_class():
        return v1_services.JobConfigService

    @staticmethod
    def get_service_job_class():
        return v1_services.JobService

    @staticmethod
    def get_serializer_job_class():
        return v1_serializers.JobSerializer

    @staticmethod
    def get_serializer_existing_program_class():
        return v1_serializers.ExistingProgramSerializer

    @staticmethod
    def get_serializer_job_config_class():
        return v1_serializers.JobConfigSerializer

    @staticmethod
    def get_serializer_upload_program_class() -> v1_serializers.UploadProgramSerializer:
        return v1_serializers.UploadProgramSerializer

    def get_serializer_class(self):
        return v1_serializers.ProgramSerializer


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


class CatalogEntryViewSet(
    views.CatalogEntryViewSet
):  # pylint: disable=too-many-ancestors
    """
    CatalogEntry view set first version. Use CatalogEntrySerializer V1.
    """

    serializer_class = v1_serializers.CatalogEntrySerializer
    permission_classes = [permissions.IsAuthenticated, CatalogUpdate]

    def get_serializer_class(self):
        return v1_serializers.CatalogEntrySerializer

    def get_queryset(self):
        return CatalogEntry.objects.all()
