"""
API V1: Available dependencies end-point.
"""
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request

from api.use_cases.files.list import FilesListUseCase
from api.v1.endpoint_decorator import endpoint
from api.utils import sanitize_name


@swagger_auto_schema(
    method="get",
    operation_description="List of available files in the user directory",
    manual_parameters=[
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="the provider name",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "function",
            openapi.IN_QUERY,
            description="the function title",
            type=openapi.TYPE_STRING,
            required=True,
        ),
    ],
    responses={
        status.HTTP_200_OK: openapi.Response(
            description="List of files",
            schema=openapi.Schema(
                type=openapi.TYPE_ARRAY, items=openapi.Items(type=openapi.TYPE_STRING)
            ),
            examples={
                "application/json": [
                    "file",
                ]
            },
        ),
        status.HTTP_401_UNAUTHORIZED: openapi.Response(
            description="Authentication credentials were not provided or are invalid."
        ),
    },
)
@endpoint("files", name="files-list")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def files_list(request: Request) -> Response:
    """
    List user files end-point
    """
    user = request.user
    provider_name = sanitize_name(request.query_params.get("provider", None))
    function_title = sanitize_name(request.query_params.get("function", None))

    if function_title is None:
        return Response(
            {"message": "Qiskit Function title is mandatory"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        files = FilesListUseCase().execute(user, provider_name, function_title)
    except ValueError as error:
        return Response(
            error.args,
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({"results": files})
