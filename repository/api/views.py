"""
Django Rest framework views for api application:
    - Nested Program ViewSet

Version views inherit from the different views.
"""

from rest_framework import permissions
from rest_framework import viewsets

from .models import QuantumFunction


class QuantumFunctionViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    QuantumFunction ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "quantum-functions"

    queryset = QuantumFunction.objects.all().order_by("created")
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        query_params = self.request.query_params
        queryset = QuantumFunction.objects.all().order_by("created")

        # if name is specified in query parameters
        title = query_params.get("title", None)
        if title:
            queryset = queryset.filter(title__exact=title)
        return queryset
