from api import views
from . import serializers as v1_serializers


class NestedProgramViewSet(views.NestedProgramViewSet):
    """
    TODO: documentation here
    """

    serializer_class = v1_serializers.NestedProgramSerializer
