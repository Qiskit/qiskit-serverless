"""
Views api for V1.
"""

from rest_framework import permissions


from api import views
from api.models import NestedProgram, Job
from api.permissions import IsOwner
from . import serializers as v1_serializers


class NestedProgramViewSet(
    views.NestedProgramViewSet
):  # pylint: disable=too-many-ancestors
    """
    Nested program view set first version. Use NestedProgramSerializer V1.
    """

    queryset = NestedProgram.objects.all()
    serializer_class = v1_serializers.NestedProgramSerializer
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_serializer_job_class():
        return v1_serializers.JobSerializer

    def get_serializer_class(self):
        return v1_serializers.NestedProgramSerializer


class JobViewSet(views.JobViewSet):  # pylint: disable=too-many-ancestors
    """
    Job view set first version. Use JobSerializer V1.
    """

    queryset = Job.objects.all()
    serializer_class = v1_serializers.JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer
