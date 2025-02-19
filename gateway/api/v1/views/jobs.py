"""
Jobs view api for V1.
"""

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
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
        operation_description="List provider Jobs",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=True)},
    )
    @action(methods=["GET"], detail=False, url_path="provider")
    def provider_list(self, request):
        return super().provider_list(request)

    @swagger_auto_schema(
        operation_description="Save the result of a job",
        responses={status.HTTP_200_OK: v1_serializers.JobSerializer(many=False)},
    )
    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):
        return super().result(request, pk)

    @swagger_auto_schema(
        operation_description="Stop a job",
    )
    @action(methods=["POST"], detail=True)
    def stop(self, request, pk=None):
        return super().stop(request, pk)

    ### We are not returning serializers in the rest of the end-points
