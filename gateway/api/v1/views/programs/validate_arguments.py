"""API endpoint for validating arguments against a Qiskit Function schema."""

import logging
from typing import cast

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.validate_arguments import ValidateArgumentsUseCase
from api.utils import parse_title_and_provider, sanitize_name
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.validate_arguments")


class InputSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Request body for the /programs/validate_arguments endpoint."""

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
    provider = serializers.CharField(required=False, allow_null=True)

    class Meta:
        ref_name = "ProgramsValidateArgumentsInput"

    def validate_title(self, value):
        """Sanitize title."""
        sanitized = sanitize_name(value)
        if not sanitized:
            raise serializers.ValidationError("Invalid title.")
        return sanitized

    def validate_provider(self, value):
        """Sanitize provider name."""
        return sanitize_name(value) if value else value


@swagger_auto_schema(
    method="post",
    operation_description="Validate arguments against a Qiskit Function schema without creating a job",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: "{'valid': true}",
        status.HTTP_400_BAD_REQUEST: "{'message': '...', 'path': [...]}",
    },
)
@endpoint("programs/validate_arguments", method="POST", name="programs-validate-arguments")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def validate_arguments(request: Request) -> Response:
    """Validates arguments against the function schema without creating a job."""
    user = request.user
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)

    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    function_title, provider_name = parse_title_and_provider(
        serializer.validated_data.get("title"),
        serializer.validated_data.get("provider"),
    )
    arguments = serializer.validated_data.get("arguments")

    logger.info(
        "[programs-validate-arguments] user_id=%s program=%s provider=%s accessible_functions=%s",
        user.id,
        function_title,
        provider_name,
        accessible_functions,
    )

    ValidateArgumentsUseCase().execute(user, accessible_functions, function_title, provider_name, arguments)

    logger.info(
        "[programs-validate-arguments] user_id=%s program=%s provider=%s | Arguments validated ok",
        user.id,
        function_title,
        provider_name,
    )
    return Response({"valid": True}, status=status.HTTP_200_OK)
