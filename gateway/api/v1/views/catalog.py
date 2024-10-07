"""
Catalog views api for V1.
"""

# pylint: disable=duplicate-code
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action

from api import views
from api.v1 import serializers as v1_serializers


class CatalogViewSet(views.CatalogViewSet):
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    @staticmethod
    def get_serializer_retrieve_catalog(*args, **kwargs):
        return v1_serializers.RetrieveCatalogSerializer(*args, **kwargs)

    serializer_class = v1_serializers.ListCatalogSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @swagger_auto_schema(
        operation_description="List public functions for catalog",
        responses={status.HTTP_200_OK: v1_serializers.ListCatalogSerializer(many=True)},
    )
    def list(self, request):
        return super().list(request)

    @swagger_auto_schema(
        operation_description="Get a specific public function for catalog",
        responses={
            status.HTTP_200_OK: v1_serializers.RetrieveCatalogSerializer(many=False)
        },
    )
    def retrieve(self, request, pk=None):
        return super().retrieve(request, pk)

    @swagger_auto_schema(
        operation_description="Get a specific public function in the catalog by title",
        responses={
            status.HTTP_200_OK: v1_serializers.RetrieveCatalogSerializer(many=False)
        },
    )
    @action(methods=["GET"], detail=False)
    def get_by_title(self, request):
        return super().get_by_title(request)
