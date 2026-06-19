"""
Programs view api for V1.
"""

from rest_framework import permissions

from api import views
from api.v1 import serializers as v1_serializers


class ProgramViewSet(views.ProgramViewSet):
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    serializer_class = v1_serializers.ProgramSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticated]
