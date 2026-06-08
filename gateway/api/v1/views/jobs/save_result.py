"""
Save result for a job API endpoint
"""

# pylint: disable=duplicate-code, abstract-method

import logging
from typing import cast
from uuid import UUID

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseRedirect
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response


from api import serializers as api_serializers
from api.access_policies.jobs import JobAccessPolicies
from api.domain.exceptions.job_not_found_exception import JobNotFoundException
from api.use_cases.jobs.save_result import JobSaveResultUseCase
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.models import Job, Program
from core.services.storage import get_result_storage
from core.services.storage.result_storage_fleets import FleetsResultStorage

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
    method="post",
    operation_description="Save the result for a job.",
    request_body=InputSerializer,
    responses={
        status.HTTP_200_OK: JobSerializer(many=False),
        **standard_error_responses(
            not_found_example="Job [XXXX] not found",
        ),
    },
)
@endpoint("jobs/<uuid:job_id>/result", name="jobs-result")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def save_result(request: Request, job_id: UUID) -> Response:
    """
    GET: Retrieve the result for a job.
        Returns 302 redirect to a presigned COS URL (Fleet, result ready),
        204 No Content (no result yet), or 200 JSON with result field (Ray).

    POST: Save a result payload into the specified job.

    Args:
        request: The HTTP request.
        job_id: Job identifier (UUID path parameter).

    Returns:
        Response containing the updated serialized job (POST) or the result (GET).
    """
    user = cast(AbstractUser, request.user)

    if request.method == "GET":
        try:
            job = Job.objects.get(id=job_id)
        except ObjectDoesNotExist as exc:
            raise JobNotFoundException(str(job_id)) from exc
        if not JobAccessPolicies.can_read_result(user, job):
            raise JobNotFoundException(str(job_id))
        if job.program.runner == Program.FLEETS:
            try:
                url = FleetsResultStorage(job).get_url()
            except (ValueError, NotImplementedError):
                url = None
            if url:
                logger.info("[jobs-result] user_id=%s job_id=%s | Redirecting to presigned URL", user.id, job_id)
                return HttpResponseRedirect(url)
            return Response(status=status.HTTP_204_NO_CONTENT)
        # Ray path
        raw = get_result_storage(job).get()
        logger.info("[jobs-result] user_id=%s job_id=%s | Result retrieved ok", user.id, job_id)
        return Response({"result": raw})

    # POST
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
