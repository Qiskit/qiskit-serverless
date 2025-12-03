"""
API endpoint to handle runtime jobs.
"""

# pylint: disable=abstract-method

from typing import Any
from uuid import UUID

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api import serializers as api_serializers
from api.use_cases.jobs.associate_runtime_jobs import (
    AssociateRuntimeJobsUseCase,
)
from api.use_cases.jobs.get_runtime_jobs import GetRuntimeJobsUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses


class InputSerializer(serializers.Serializer):
    """
    Validates the request body for associating runtime jobs to a serverless job.
    """

    runtime_job = serializers.CharField(required=True)
    runtime_session = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "RuntimeJobsInputSerializer"


class RuntimeJobSerializer(api_serializers.RuntimeJobSerializer):
    """
    Runtime job serializer fileds.
    """

    class Meta(api_serializers.RuntimeJobSerializer.Meta):
        fields = ["runtime_job", "runtime_session"]


def serialize_output(out_runtime_jobs: Any) -> dict[str, Any]:
    """
    Build the response payload for runtime_jobs.

    Args:
        job: Updated job instance.

    Returns:
        A dictionary containing the serialized runtime jobs under the 'runtime_jobs' key.
    """
    return {"runtime_jobs": RuntimeJobSerializer(out_runtime_jobs, many=True).data}


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve runtime jobs associated with a job.",
    responses={
        status.HTTP_200_OK: RuntimeJobSerializer,
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
            unauthorized_example="Authentication credentials were not provided or are invalid.",
        ),
    },
)
@swagger_auto_schema(
    method="post",
    operation_description="Associate a runtime job with a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: serializers.Serializer(),
        **standard_error_responses(
            bad_request_example="Got empty `runtime_job` field. Please, specify `runtime_job`.",
            not_found_example="Job [XXXX] not found",
            unauthorized_example="Authentication credentials were not provided or are invalid.",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/runtime_jobs", name="jobs-runtime-jobs")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def runtime_jobs(request: Request, job_id: UUID) -> Response:
    """
    Handle RuntimeJob objects associated with a Job.

    GET: Retrieve runtime jobs.
    POST: Associate a new runtime job.
    """
    if request.method == "POST":
        serializer = InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        runtime_job = serializer.validated_data.get("runtime_job")
        runtime_session = serializer.validated_data.get("runtime_session")
        message = AssociateRuntimeJobsUseCase().execute(
            job_id, runtime_job, runtime_session
        )
        return Response({"message": message})

    if request.method == "GET":
        out_runtime_jobs = GetRuntimeJobsUseCase().execute(job_id)
        return Response(serialize_output(out_runtime_jobs))

    raise MethodNotAllowed(request.method)
