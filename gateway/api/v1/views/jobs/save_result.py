"""
Save result for a job API endpoint
"""

# pylint: disable=duplicate-code, abstract-method

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.http import HttpResponseRedirect
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response


from api import serializers as api_serializers
from api.use_cases.jobs.get_result import GetJobResultUseCase
from api.use_cases.jobs.save_result import JobSaveResultUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.models import Job

logger = logging.getLogger("api.api.v1.views.jobs.save_result")


class InputSerializer(serializers.Serializer):
    """
    Validate and sanitize the input
    """

    result = serializers.CharField(required=True)

    class Meta:
        """Meta class to define input serializer name"""

        ref_name = "JobsSaveResultInputSerializer"


class ProgramSerializer(api_serializers.ProgramSerializer):
    """
    Program serializer first version. Include basic fields from the initial model.
    """

    class Meta(api_serializers.ProgramSerializer.Meta):
        fields = [
            "id",
            "title",
            "entrypoint",
            "artifact",
            "dependencies",
            "provider",
            "description",
            "documentation_url",
            "type",
        ]
        ref_name = "JobsSaveResultProgramSerializer"


class JobSerializer(api_serializers.JobSerializer):
    """
    Job serializer first version. Include basic fields from the initial model.
    """

    program = ProgramSerializer(many=False)

    class Meta(api_serializers.JobSerializer.Meta):
        fields = ["id", "result", "status", "program", "created", "sub_status"]
        ref_name = "JobsSaveResultJobSerializer"


def serialize_output(job: Job):
    """
    Serialize the job for the response.

    Args:
        job: The updated job instance.

    Returns:
        Serialized job as a dictionary.
    """
    return JobSerializer(job).data


@swagger_auto_schema(
    method="get",
    operation_description=(
        "Retrieve the result for a job.\n\n"
        "Fleet jobs return a `302` redirect to a presigned COS URL — the client should follow "
        "the redirect and decode the JSON body from COS directly. "
        "If the result is not ready yet, the response is `204 No Content`.\n\n"
        'Ray jobs return `200` with a JSON body `{"result": "<raw JSON string>"}` '
        "containing the raw result string."
    ),
    responses={
        status.HTTP_302_FOUND: openapi.Response(
            description="Fleet job — result ready. Follow the Location header to download the raw result from COS.",
            headers={"Location": openapi.Schema(type=openapi.TYPE_STRING, description="Presigned COS URL")},
        ),
        status.HTTP_204_NO_CONTENT: openapi.Response(
            description="Fleet job — result not ready yet.",
        ),
        status.HTTP_200_OK: openapi.Response(
            description="Ray job — result returned inline.",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={"result": openapi.Schema(type=openapi.TYPE_STRING, description="Raw JSON result string")},
            ),
        ),
        **standard_error_responses(not_found_example="Job [XXXX] not found"),
    },
)
@endpoint("jobs/<uuid:job_id>/result", method="GET", name="jobs-result")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_result(request: Request, job_id: UUID) -> Response:
    """
    Retrieve the result for a job.

    Returns 302 redirect to a presigned COS URL (Fleet, result ready),
    204 No Content (no result yet), or 200 JSON with result field (Ray).
    """
    user = cast(AbstractUser, request.user)
    outcome = GetJobResultUseCase().execute(job_id, user)
    if outcome.redirect_url:
        logger.info("[jobs-get-result] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
        return HttpResponseRedirect(outcome.redirect_url)
    if outcome.raw_result is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    logger.info("[jobs-get-result] user_id=%s job_id=%s | Result retrieved ok", user.id, job_id)
    return Response({"result": outcome.raw_result})


@swagger_auto_schema(
    method="post",
    operation_description="Save the result for a job. Deprecated: functions now write results directly to COS.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: JobSerializer(many=False),
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/result", method="POST", name="jobs-result")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def save_result(request: Request, job_id: UUID) -> Response:
    """
    Save a result payload into the specified job.

    Deprecated: functions now write results directly to COS.
    """
    user = cast(AbstractUser, request.user)
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    result = serializer.validated_data["result"]

    job = JobSaveResultUseCase().execute(job_id, user, result)
    logger.info(
        "[jobs-save-result] user_id=%s job_id=%s program=%s | Result saved ok",
        user.id,
        job_id,
        job.program.title if job.program else "",
    )
    return Response(serialize_output(job))
