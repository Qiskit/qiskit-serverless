"""Permissions."""

from rest_framework import permissions
from core.models import RuntimeJob


class IsOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, RuntimeJob):
            return obj.job.author == request.user
        return obj.author == request.user
