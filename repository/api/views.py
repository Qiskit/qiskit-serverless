"""
Django Rest framework views for api application:
    - Nested Program ViewSet

Version views inherit from the different views.
"""

from rest_framework import permissions
from rest_framework import viewsets

from .models import NestedProgram


class AuthorOrReadOnly(permissions.BasePermission):
    """
    Author Or ReadOnly permission.
    """

    def has_permission(self, request, view):
        if request.OIDC != "none":
            return True
        return False

    def has_object_permission(self, request, view, obj):
        if obj.author == request.OIDC:
            return True
        return False


class NestedProgramViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Nested Program ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "nested-programs"

    queryset = NestedProgram.objects.all().order_by("created")
    permission_classes = [AuthorOrReadOnly]

    def get_queryset(self):
        query_params = self.request.query_params
        queryset = NestedProgram.objects.all().order_by("created")

        # if name is specified in query parameters
        title = query_params.get("title", None)
        if title:
            queryset = queryset.filter(title__exact=title)
        return queryset
