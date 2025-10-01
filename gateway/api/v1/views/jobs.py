"""
Jobs view api for V1.
"""

from rest_framework import permissions
from rest_framework.pagination import LimitOffsetPagination

from api import views
from api.permissions import IsOwner
from api.v1 import serializers as v1_serializers


class JobViewSet(views.JobViewSet):
    """
    Job view set first version. Use JobSerializer V1.
    """

    serializer_class = v1_serializers.JobSerializer
    pagination_class = LimitOffsetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_serializer_class(self):
        return v1_serializers.JobSerializer

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        """
        Returns a `JobSerializer` instance
        """
        return v1_serializers.JobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_job_without_result(*args, **kwargs):
        """
        Returns a `JobSerializerWithoutResult` instance
        """
        return v1_serializers.JobSerializerWithoutResult(*args, **kwargs)
