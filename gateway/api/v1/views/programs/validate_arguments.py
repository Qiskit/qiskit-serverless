"""API endpoint for validating arguments against a Qiskit Function schema."""

import json
import logging
from typing import cast

import jsonschema
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.access_policies.jobs import JobAccessPolicies
from api.use_cases.validate_arguments import validate_arguments as validate_arguments_use_case
from api.utils import sanitize_name
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)

logger = logging.getLogger("api.api.v1.views.programs.validate_arguments")


class InputSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Request body for the /programs/validate_arguments endpoint."""

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
    provider = serializers.CharField(required=False, allow_null=True)

    class Meta:
        ref_name = "ProgramsValidateArgumentsInput"


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
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    provider_name = sanitize_name(serializer.data.get("provider"))
    function_title = sanitize_name(serializer.data.get("title"))

    logger.info(
        "[programs-validate-arguments] user_id=%s program=%s provider=%s accessible_functions=%s",
        user.id,
        function_title,
        provider_name,
        accessible_functions,
    )

    function = None
    if provider_name:
        function = Function.objects.get_function_by_permission(
            user=user,
            function_title=function_title,
            provider_name=provider_name,
            accessible_functions=accessible_functions,
            permission=PLATFORM_PERMISSION_RUN,
            legacy_permission_name=RUN_PROGRAM_PERMISSION,
        )
    else:
        if JobAccessPolicies.can_create(user=user, accessible_functions=accessible_functions):
            function = Function.objects.get_user_function(user, function_title)

    if function is None:
        return Response(
            {"message": f"Qiskit Pattern [{function_title}] was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    arguments = serializer.data.get("arguments")
    try:
        validate_arguments_use_case(function, arguments)
    except jsonschema.ValidationError as exc:
        return Response(
            {"message": exc.message, "path": [*exc.path]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except json.JSONDecodeError as exc:
        return Response(
            {"message": f"arguments is not valid JSON: {exc.msg}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    logger.info(
        "[programs-validate-arguments] user_id=%s program=%s provider=%s | Arguments validated ok",
        user.id,
        function_title,
        provider_name,
    )
    return Response({"valid": True}, status=status.HTTP_200_OK)
