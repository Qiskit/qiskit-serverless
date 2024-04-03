"""Permissions."""

from rest_framework import permissions
from api.models import RuntimeJob


class IsOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, RuntimeJob):
            return obj.job.author == request.user
        return obj.author == request.user


class CatalogUpdate(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to update it.
    """

    def has_object_permission(self, request, view, obj):
        if request.method == "GET":
            return True
        return obj.program.author == request.user
