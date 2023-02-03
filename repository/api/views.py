from rest_framework import viewsets
from rest_framework import permissions
from .models import NestedProgram
from .serializers import NestedProgramSerializer


class NestedProgramViewSet(viewsets.ModelViewSet):
    """
    TODO: documentation here
    """

    queryset = NestedProgram.objects.all().order_by("created")
    serializer_class = NestedProgramSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
