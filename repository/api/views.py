from rest_framework import viewsets
from rest_framework import permissions
from .models import NestedProgram


class NestedProgramViewSet(viewsets.ModelViewSet):
    """
    TODO: documentation here
    """

    BASE_NAME = "nested-programs"

    queryset = NestedProgram.objects.all().order_by("created")
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
