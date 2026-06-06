"""
Result endpoint: GET (fetch) and POST (save) for a job result.
"""

# pylint: disable=duplicate-code, abstract-method

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.http import HttpResponseRedirect
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response


from api import serializers as api_serializers
from api.use_cases.jobs.get_result import GetJobResultUseCase
from api.use_cases.jobs.save_result import JobSaveResultUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
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


@endpoint("jobs/<uuid:job_id>/result", name="jobs-result")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def result(request: Request, job_id: UUID) -> Response:
    """
    GET: Retrieve the result for a job.
        Returns 302 redirect to a presigned COS URL (Fleet, result ready),
        204 No Content (no result yet), or 200 JSON with result field (Ray).

    POST: Save a result payload into the specified job.

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).
    """
    user = cast(AbstractUser, request.user)

    if request.method == "GET":
        fetch = GetJobResultUseCase().execute(job_id, user)
        if fetch.redirect_url:
            logger.info("[jobs-result] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
            return HttpResponseRedirect(fetch.redirect_url)
        if fetch.raw_result is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        logger.info("[jobs-result] user_id=%s job_id=%s | Result retrieved ok", user.id, job_id)
        return Response({"result": fetch.raw_result})

    # POST
    serializer = InputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    job = JobSaveResultUseCase().execute(job_id, user, serializer.validated_data["result"])
    logger.info(
        "[jobs-save-result] user_id=%s job_id=%s program=%s | Result saved ok",
        user.id,
        job_id,
        job.program.title if job.program else "",
    )
    return Response(serialize_output(job))
