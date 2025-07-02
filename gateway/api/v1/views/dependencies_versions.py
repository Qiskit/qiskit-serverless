"""
API V1: Available dependencies end-point.
"""
from typing import Dict
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from pkg_resources import Requirement
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from api.use_cases.dependencies_versions import (
    AvailableDependenciesVersionsUseCase,
)


def serialize_output(data: Dict[str, Requirement]):
    """
    Prepare de output for the end-point
    """
    return [str(dep) for dep in data.values()]


@swagger_auto_schema(
    method="get",
    operation_description="Get the list of available "
    "dependencies and its versions for creating functions",
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="List of strings",
            schema=openapi.Schema(
                type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_STRING)
            ),
        )
    },
)
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def dependencies_versions(_):
    """
    Available dependencies versions end-point
    """
    dependencies = AvailableDependenciesVersionsUseCase().execute()

    return Response(serialize_output(dependencies))
