"""API endpoint for retrieving a Qiskit Function's size catalog."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.get_sizes import GetFunctionSizesUseCase
from api.utils import parse_title_and_provider
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.get_sizes")


class OutputSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Size catalog for a single function.

    ``sizes`` maps each declared size label to the bare compute-profile id it
    resolves to; ``default_size`` is the label used when a run omits a size, or
    null when the function declares no default.
    """

    sizes = serializers.DictField(child=serializers.CharField())
    default_size = serializers.CharField(allow_null=True)

    class Meta:
        ref_name = "ProgramsGetSizesOutput"


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve the declared sizes and default size of a Qiskit Function",
    manual_parameters=[
        openapi.Parameter(
            "title",
            openapi.IN_PATH,
            description="The title of the function",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="The provider in case the function is owned by a provider",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={
        status.HTTP_200_OK: OutputSerializer,
        **standard_error_responses(not_found_example="Qiskit Function [XXX] doesn't exist."),
    },
)
@endpoint("programs/get_by_title/<str:title>/sizes", method="GET", name="programs-get-sizes")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_sizes(request: Request, title: str) -> Response:
    """Retrieve the size catalog and default size of a single Qiskit Function."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    # The route is <str:title> (converter "[^/]+"), so a "provider/title" form cannot arrive here;
    # the provider always comes from the query parameter. The shared helper handles both forms so
    # the behavior stays identical to the other title-scoped endpoints.
    function_title, provider_name = parse_title_and_provider(title, request.query_params.get("provider"))
    logger.info(
        "[programs-get-sizes] user_id=%s program=%s provider=%s",
        user.id,
        function_title,
        provider_name,
    )

    sizes, default_size = GetFunctionSizesUseCase().execute(user, accessible_functions, function_title, provider_name)

    payload = {
        "sizes": {size.function_size: size.compute_profile.compute_profile_id for size in sizes},
        "default_size": default_size.function_size if default_size else None,
    }
    return Response(OutputSerializer(payload).data)
