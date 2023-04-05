"""
Views api for V1.
"""

from rest_framework import permissions


from api import views
from api.models import QuantumFunction, Job
from api.permissions import IsOwner
from . import serializers as v1_serializers


class QuantumFunctionViewSet(
    views.QuantumFunctionViewSet
):  # pylint: disable=too-many-ancestors
    """
    Quantum function view set first version. Use QuantumFunctionSerializer V1.
    """

    queryset = QuantumFunction.objects.all()
    serializer_class = v1_serializers.QuantumFunctionSerializer
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_serializer_job_class():
        return v1_serializers.JobSerializer

    def get_serializer_class(self):
        return v1_serializers.QuantumFunctionSerializer


class JobViewSet(views.JobViewSet):  # pylint: disable=too-many-ancestors
    """
    Job view set first version. Use JobSerializer V1.
    """

    queryset = Job.objects.all()
    serializer_class = v1_serializers.JobSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer
