"""
Views api for V1.
"""

from api import views
from . import serializers as v1_serializers


class QuantumFunctionViewSet(
    views.QuantumFunctionViewSet
):  # pylint: disable=too-many-ancestors
    """
    Program view set first version. Use QuantumFunctionSerializer V1.
    """

    serializer_class = v1_serializers.QuantumFunctionSerializer
