"""
Django Rest framework views for api application:
    - Nested Program ViewSet

Version views inherit from the different views.
"""

from rest_framework import permissions
from rest_framework import viewsets

from .models import NestedProgram


class NestedProgramViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Nested Program ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "nested-programs"

    queryset = NestedProgram.objects.all().order_by("created")
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        query_params = self.request.query_params
        queryset = NestedProgram.objects.all().order_by("created")

        # if name is specified in query parameters
        name = query_params.get("name", None)
        if name:
            queryset = queryset.filter(title__exact=name)
        return queryset
