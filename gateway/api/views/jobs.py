"""
Django Rest framework Job views for api application:

Version views inherit from the different views.
"""
import logging
import os

# pylint: disable=duplicate-code
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from rest_framework.decorators import action
from rest_framework import viewsets, status
from rest_framework.response import Response

from api.models import RuntimeJob
from api.repositories.jobs import JobsRepository, JobFilters
from api.repositories.functions import FunctionRepository
from api.repositories.providers import ProviderRepository
from api.serializers import (
    JobSerializer,
    JobSerializerWithoutResult,
    RuntimeJobSerializer,
)
from api.decorators.trace_decorator import trace_decorator_factory

# pylint: disable=duplicate-code
logger = logging.getLogger("gateway")
resource = Resource(attributes={SERVICE_NAME: "QiskitServerless-Gateway"})
tracer_provider = TracerProvider(resource=resource)
otel_exporter = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint=os.environ.get(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"
        ),
        insecure=bool(int(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "0"))),
    )
)
tracer_provider.add_span_processor(otel_exporter)
if bool(int(os.environ.get("OTEL_ENABLED", "0"))):
    trace._set_tracer_provider(  # pylint: disable=protected-access
        tracer_provider, log=False
    )

_trace = trace_decorator_factory("jobs")


class JobViewSet(viewsets.GenericViewSet):
    """
    Job ViewSet configuration using GenericViewSet.
    """

    BASE_NAME = "jobs"

    jobs_repository = JobsRepository()
    function_repository = FunctionRepository()
    provider_repository = ProviderRepository()

    def get_serializer_class(self):
        """
        Returns the default serializer class for the view.
        """
        return self.serializer_class

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        """
        Returns a `JobSerializer` instance
        """
        return JobSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_job_without_result(*args, **kwargs):
        """
        Returns a `JobSerializerWithoutResult` instance
        """
        return JobSerializerWithoutResult(*args, **kwargs)

    def get_queryset(self):
        """
        Returns a filtered queryset of `Job` objects based on the `filter` query parameter.
        - If `filter=catalog`, returns jobs authored by the user with an existing provider.
        - If `filter=serverless`, returns jobs authored by the user without a provider.
        - Otherwise, returns all jobs authored by the user.

        Returns:
            QuerySet: A filtered queryset of `Job` objects ordered by creation date (descending).
        """
        type_filter = self.request.query_params.get("filter")
        user = self.request.user

        filters = JobFilters(filter=type_filter)

        queryset, _ = self.jobs_repository.get_user_jobs(user=user, filters=filters)

        return queryset

    # @_trace
    # @action(methods=["POST"], detail=True)
    # def stop(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
    #     """Stops job"""
    #     job = self.get_object()
    #     if not job.in_terminal_state():
    #         job.status = Job.STOPPED
    #         job.save(update_fields=["status"])
    #     message = "Job has been stopped."
    #     runtime_jobs = self.get_runtime_job(job)
    #     if runtime_jobs and len(runtime_jobs) != 0:
    #         if request.data.get("service"):
    #             service = QiskitRuntimeService(
    #                 **json.loads(request.data.get("service"), cls=json.JSONDecoder)[
    #                     "__value__"
    #                 ]
    #             )
    #             for runtime_job_entry in runtime_jobs:
    #                 jobinstance = service.job(runtime_job_entry.runtime_job)
    #                 if jobinstance:
    #                     try:
    #                         logger.info("canceling [%s]", runtime_job_entry.runtime_job)
    #                         jobinstance.cancel()
    #                     except RuntimeInvalidStateError:
    #                         logger.warning("cancel failed")

    #                     if jobinstance.session_id:
    #                         service._get_api_client().cancel_session(  # pylint: disable=protected-access
    #                             jobinstance.session_id
    #                         )

    #     if job.compute_resource:
    #         if job.compute_resource.active:
    #             job_handler = get_job_handler(job.compute_resource.host)
    #             if job_handler is not None:
    #                 was_running = job_handler.stop(job.ray_job_id)
    #                 if not was_running:
    #                     message = "Job was already not running."
    #             else:
    #                 logger.warning(
    #                     "Compute resource is not accessible %s",
    #                     job.compute_resource,
    #                 )
    #     return Response({"message": message})

    @_trace
    @action(methods=["POST"], detail=True)
    def runtime_jobs(
        self, request, pk=None
    ):  # pylint: disable=invalid-name,unused-argument
        """Add RuntimeJob to job"""
        if not request.data.get("runtime_job"):
            return Response(
                {
                    "message": "Got empty `runtime_job` field. Please, specify `runtime_job`."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        job = self.get_object()
        runtimejob = RuntimeJob(
            job=job,
            runtime_job=request.data.get("runtime_job"),
            runtime_session=request.data.get("runtime_session"),
        )
        runtimejob.save()
        message = "RuntimeJob is added."
        return Response({"message": message})

    @_trace
    @action(methods=["GET"], detail=True)
    def list_runtime_jobs(self, job, pk=None):
        """Get runtime jobs for serverless job"""
        job = self.get_object()
        runtime_jobs = RuntimeJob.objects.filter(job=job)
        serializer = RuntimeJobSerializer(runtime_jobs, many=True)
        return Response({"runtime_jobs": serializer.data})
