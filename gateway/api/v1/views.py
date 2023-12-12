"""
Views api for V1.
"""

from rest_framework import permissions


from api import views
from api.models import Program, Job
from api.permissions import IsOwner
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
    def get_serializer_job_class():
        return v1_serializers.JobSerializer

    @staticmethod
    def get_serializer_existing_program_class():
        return v1_serializers.ExistingProgramSerializer

    @staticmethod
    def get_serializer_job_config_class():
        return v1_serializers.JobConfigSerializer

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
