"""API endpoint for running a Qiskit Function."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.domain.authentication.channel import Channel
from api.use_cases.programs.run import RunFunctionUseCase
from api.use_cases.programs.run_input import RunFunctionInput
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.run")


@swagger_auto_schema(
    method="post",
    operation_description="Run an existing Qiskit Function",
    request_body=v1_serializers.RunProgramSerializer,
    responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
)
@endpoint("programs/run", method="POST", name="programs-run")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def run_program(request: Request) -> Response:
    """Enqueue a job for an existing Qiskit Function."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)

    serializer = v1_serializers.RunProgramSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    title = serializer.validated_data.get("title")
    provider_name = serializer.validated_data.get("provider")
    arguments = serializer.validated_data.get("arguments")
    compute_profile = serializer.validated_data.get("compute_profile")

    config_data = None
    if serializer.validated_data.get("config"):
        config_serializer = v1_serializers.JobConfigSerializer(data=serializer.validated_data["config"])
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
    logger.info("[programs-run] user_id=%s job_id=%s | Job queued ok", user.id, job.id)
    return Response(v1_serializers.RunJobSerializer(job).data)
