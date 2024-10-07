"""
Files view api for V1.
"""

from rest_framework import permissions

from api.permissions import IsOwner
from api import views


class FilesViewSet(views.FilesViewSet):
    """
    Files view set.
    """

    permission_classes = [permissions.IsAuthenticated, IsOwner]
