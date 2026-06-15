"""
Programs view api for V1.
"""

import jsonschema
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from typing import cast

from api import views
from api.access_policies.jobs import JobAccessPolicies
from api.use_cases.validate_arguments import validate_arguments as validate_arguments_use_case
from api.utils import sanitize_name
from api.v1 import serializers as v1_serializers
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)


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
        operation_description="List author Qiskit Functions",
        manual_parameters=[
            openapi.Parameter(
                "filter",
                openapi.IN_QUERY,
                description="Filters that you can apply for list: serverless, catalog or empty",
                type=openapi.TYPE_STRING,
                required=False,
            ),
        ],
        responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer(many=True)},
    )
    def list(self, request):
        return super().list(request)

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

    @swagger_auto_schema(
        operation_description="Retrieve a Qiskit Function using the title",
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
        responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="get_by_title/(?P<title>[^/.]+)")
    def get_by_title(self, request, title):
        return super().get_by_title(request, title)

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
                {"message": exc.message, "path": list(exc.path)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"valid": True}, status=status.HTTP_200_OK)
