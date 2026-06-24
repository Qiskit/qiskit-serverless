"""API endpoint for running a Qiskit Function."""

import json
import logging
import re
from typing import cast

import jsonschema
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.domain.authentication.channel import Channel
from api.use_cases.programs.run import RunFunctionUseCase
from api.use_cases.programs.run_input import RunFunctionInput
from api.utils import sanitize_name
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Job, JobConfig

logger = logging.getLogger("api.api.v1.views.programs.run")


class InputSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """Request body for the /programs/run endpoint."""

    title = serializers.CharField(max_length=255)
    arguments = serializers.CharField()
    config = serializers.JSONField()
    provider = serializers.CharField(required=False, allow_null=True)
    compute_profile = serializers.CharField(required=False, allow_null=True)

    _COMPUTE_PROFILE_RE = re.compile(r"^[a-z]+\d+[a-z]?-\d+x\d+(?:x\d+[a-z0-9]+)?$")

    class Meta:
        ref_name = "ProgramsRunInput"

    def validate_title(self, value):
        """Sanitize title."""
        return sanitize_name(value)

    def validate_provider(self, value):
        """Sanitize provider name."""
        return sanitize_name(value) if value else value

    def validate_compute_profile(self, value):
        """Validate compute profile format (e.g. 'cx3d-4x16')."""
        if value and not self._COMPUTE_PROFILE_RE.match(value):
            raise serializers.ValidationError(
                f"Invalid compute profile format: '{value}'. "
                f"Expected format: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type] "
                f"(lowercase only, e.g., 'cx3d-4x16' or 'gx3d-24x120x1a100p')"
            )
        return value


class JobConfigSerializer(serializers.ModelSerializer):
    """Config sub-serializer for Ray cluster settings."""

    workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    min_workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MIN_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    max_workers = serializers.IntegerField(
        max_value=settings.RAY_CLUSTER_WORKER_MAX_REPLICAS_MAX,
        required=False,
        allow_null=True,
    )
    auto_scaling = serializers.BooleanField(default=False, required=False, allow_null=True)

    class Meta:
        model = JobConfig
        fields = ["workers", "min_workers", "max_workers", "auto_scaling"]
        ref_name = "ProgramsRunJobConfig"


class OutputSerializer(serializers.ModelSerializer):
    """Response serializer for a queued job."""

    compute_profile = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)

    class Meta:
        model = Job
        fields = ["id", "result", "status", "program", "created", "arguments", "compute_profile"]
        ref_name = "ProgramsRunOutput"


@swagger_auto_schema(
    method="post",
    operation_description="Run an existing Qiskit Function",
    request_body=InputSerializer,
    responses={status.HTTP_200_OK: OutputSerializer},
)
@endpoint("programs/run", method="POST", name="programs-run")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def run_program(request: Request) -> Response:
    """Enqueue a job for an existing Qiskit Function."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)

    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    title = serializer.validated_data.get("title")
    provider_name = serializer.validated_data.get("provider")
    arguments = serializer.validated_data.get("arguments")
    compute_profile = serializer.validated_data.get("compute_profile")

    config_data = None
    if serializer.validated_data.get("config"):
        config_serializer = JobConfigSerializer(data=serializer.validated_data["config"])
        config_serializer.is_valid(raise_exception=True)
        config_data = dict(config_serializer.validated_data)

    channel = Channel.IBM_QUANTUM_PLATFORM
    token = ""
    instance = None
    account_id = None
    if request.auth:
        channel = request.auth.channel
        token = request.auth.token.decode()
        instance = request.auth.instance
        account_id = request.auth.account_id

    carrier = {}
    TraceContextTextMapPropagator().inject(carrier)

    logger.info(
        "[programs-run] user_id=%s title=%s provider=%s accessible_functions=%s",
        user.id,
        title,
        provider_name,
        accessible_functions,
    )

    try:
        job = RunFunctionUseCase().execute(
            user,
            accessible_functions,
            RunFunctionInput(
                title=title,
                provider_name=provider_name,
                arguments=arguments,
                config_data=config_data,
                compute_profile=compute_profile,
                channel=channel,
                token=token,
                instance=instance,
                account_id=account_id,
                carrier=carrier,
            ),
        )
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
    logger.info("[programs-run] user_id=%s job_id=%s | Job queued ok", user.id, job.id)
    return Response(OutputSerializer(job).data)
