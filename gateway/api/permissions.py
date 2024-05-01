"""Permissions."""

from rest_framework import permissions
from api.models import RuntimeJob


# Program permissions
VIEW_PROGRAM_PERMISSION = "view_program"
RUN_PROGRAM_PERMISSION = "run_program"


class IsOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, RuntimeJob):
            return obj.job.author == request.user
        return obj.author == request.user
