"""API endpoint for uploading a Qiskit Function."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.upload import UploadFunctionUseCase
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.upload")


@swagger_auto_schema(
    method="post",
    operation_description="Upload a Qiskit Function",
    request_body=v1_serializers.UploadProgramSerializer,
    responses={status.HTTP_200_OK: v1_serializers.UploadProgramSerializer},
)
@endpoint("programs/upload", method="POST", name="programs-upload")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def upload_program(request: Request) -> Response:
    """Upload or update a Qiskit Function."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-upload] user_id=%s title=%s provider=%s accessible_functions=%s",
        user.id,
        request.data.get("title"),
        request.data.get("provider"),
        accessible_functions,
    )

    function = UploadFunctionUseCase().execute(user, accessible_functions, request.data)
    logger.info(
        "[programs-upload] user_id=%s program=%s | Function uploaded ok",
        user.id,
        function.title,
    )
    return Response(v1_serializers.UploadProgramSerializer(function).data)
