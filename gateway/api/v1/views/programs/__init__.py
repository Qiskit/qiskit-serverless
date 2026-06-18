"""
Programs view api for V1.
"""

import json
import logging
from typing import cast

import jsonschema
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api import views
from api.access_policies.jobs import JobAccessPolicies
from api.use_cases.validate_arguments import validate_arguments as validate_arguments_use_case
from api.utils import sanitize_name
from api.v1 import serializers as v1_serializers
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)

logger = logging.getLogger("api.api.views.programs")


class ProgramViewSet(views.ProgramViewSet):
    """
    Quantum function view set first version. Use ProgramSerializer V1.
    """

    serializer_class = v1_serializers.ProgramSerializer
    pagination_class = None
    permission_classes = [permissions.IsAuthenticated]

    @staticmethod
    def get_serializer_job_config(*args, **kwargs):
        return v1_serializers.JobConfigSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_upload_program(*args, **kwargs):
        return v1_serializers.UploadProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_program(*args, **kwargs):
        return v1_serializers.RunProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_job(*args, **kwargs):
        return v1_serializers.RunJobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        return v1_serializers.JobSerializer(*args, **kwargs)

    @swagger_auto_schema(
        operation_description="Upload a Qiskit Function",
        request_body=v1_serializers.UploadProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.UploadProgramSerializer},
    )
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        return super().upload(request)

    @swagger_auto_schema(
        operation_description="Run an existing Qiskit Function",
        request_body=v1_serializers.RunProgramSerializer,
        responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
    )
    @action(methods=["POST"], detail=False)
    def run(self, request):
        return super().run(request)

    @endpoint_handle_exceptions
    @swagger_auto_schema(
        operation_description="Validate arguments against a Qiskit Function schema without creating a job",
        request_body=v1_serializers.ValidateArgumentsSerializer,
        responses={
            status.HTTP_200_OK: "{'valid': true}",
            status.HTTP_400_BAD_REQUEST: "{'message': '...', 'path': [...]}",
        },
    )
    @action(methods=["POST"], detail=False)
    def validate_arguments(self, request):
        """Validates arguments against the function schema without creating a job."""
        serializer = v1_serializers.ValidateArgumentsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        author = request.user
        provider_name = sanitize_name(serializer.data.get("provider"))
        function_title = sanitize_name(serializer.data.get("title"))
        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-validate-arguments] user_id=%s program=%s provider=%s accessible_functions=%s",
            author.id,
            function_title,
            provider_name,
            accessible_functions,
        )

        function = None
        if provider_name:
            function = Function.objects.get_function_by_permission(
                user=author,
                function_title=function_title,
                provider_name=provider_name,
                accessible_functions=accessible_functions,
                permission=PLATFORM_PERMISSION_RUN,
                legacy_permission_name=RUN_PROGRAM_PERMISSION,
            )
        else:
            if JobAccessPolicies.can_create(user=author, accessible_functions=accessible_functions):
                function = Function.objects.get_user_function(author, function_title)

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
            author.id,
            function_title,
            provider_name,
        )
        return Response({"valid": True}, status=status.HTTP_200_OK)
