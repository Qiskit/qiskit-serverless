"""
Django Rest framework Job views for api application:

Version views inherit from the different views.
"""
import json
import logging
import os

# pylint: disable=duplicate-code
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework.decorators import action
from rest_framework import viewsets, status
from rest_framework.response import Response

from qiskit_ibm_runtime import RuntimeInvalidStateError, QiskitRuntimeService
from api.models import Job, RuntimeJob
from api.ray import get_job_handler
from api.views.enums.type_filter import TypeFilter
from api.services.result_storage import ResultStorage
from api.access_policies.jobs import JobAccessPolocies
from api.repositories.jobs import JobsRepository
from api.serializers import JobSerializer, JobSerializerWithoutResult

# pylint: disable=duplicate-code
logger = logging.getLogger("gateway")
resource = Resource(attributes={SERVICE_NAME: "QiskitServerless-Gateway"})
provider = TracerProvider(resource=resource)
otel_exporter = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint=os.environ.get(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"
        ),
        insecure=bool(int(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "0"))),
    )
)
provider.add_span_processor(otel_exporter)
if bool(int(os.environ.get("OTEL_ENABLED", "0"))):
    trace._set_tracer_provider(provider, log=False)  # pylint: disable=protected-access


class JobViewSet(viewsets.GenericViewSet):
    """
    Job ViewSet configuration using GenericViewSet.
    """

    BASE_NAME = "jobs"

    jobs_repository = JobsRepository()

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
        if type_filter:
            if type_filter == TypeFilter.CATALOG:
                return self.jobs_repository.get_user_jobs_with_provider(
                    self.request.user
                )
            if type_filter == TypeFilter.SERVERLESS:
                return self.jobs_repository.get_user_jobs_without_provider(
                    self.request.user
                )
        return Job.objects.filter(author=self.request.user).order_by("-created")

    def retrieve(self, request, pk=None):  # pylint: disable=unused-argument
        """Get job:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.retrieve", context=ctx):

            author = self.request.user
            job = self.jobs_repository.get_job_by_id(pk)
            if job is None:
                return Response(
                    {"message": f"Job [{pk}] nor found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not JobAccessPolocies.can_access(author, job):
                return Response(
                    {"message": f"Job [{pk}] was not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            is_provider_job = job.program and job.program.provider
            if is_provider_job:
                serializer = self.get_serializer_job_without_result(job)
                return Response(serializer.data)

            result_store = ResultStorage(author.username)
            result = result_store.get(str(job.id))
            if result is not None:
                job.result = result

            serializer = self.get_serializer_job(job)

            return Response(serializer.data)

    def list(self, request):
        """List jobs:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.list", context=ctx):
            type_filter = self.request.query_params.get("filter")
            user = self.request.user
            queryset = self.filter_queryset(
                self.get_queryset(type_filter, user)
            )

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer_job_without_result(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer_job_without_result(queryset, many=True)
        return Response(serializer.data)

    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Save result of a job."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.result", context=ctx):
            author = self.request.user
            job = self.jobs_repository.get_job_by_id(pk)
            if job is None:
                return Response(
                    {"message": f"Job [{pk}] nor found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            can_save_result = JobAccessPolocies.can_save_result(author, job)
            if not can_save_result:
                return Response(
                    {"message": f"Job [{job.id}] nor found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            job.result = json.dumps(request.data.get("result"))
            result_storage = ResultStorage(author.username)
            result_storage.save(job.id, job.result)

            serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["GET"], detail=True)
    def logs(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Returns logs from job."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.logs", context=ctx):
            job = Job.objects.filter(pk=pk).first()
            if job is None:
                logger.warning("Job [%s] not found", pk)
                return Response(status=404)

            logs = job.logs
            author = self.request.user
            if job.program and job.program.provider:
                provider_groups = job.program.provider.admin_groups.all()
                author_groups = author.groups.all()
                has_access = any(group in provider_groups for group in author_groups)
                if has_access:
                    return Response({"logs": logs})
                return Response({"logs": "No available logs"})

            if author == job.author:
                return Response({"logs": logs})
            return Response({"logs": "No available logs"})

    def get_runtime_job(self, job):
        """get runtime job for job"""
        return RuntimeJob.objects.filter(job=job)

    @action(methods=["POST"], detail=True)
    def stop(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Stops job"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.stop", context=ctx):
            job = self.get_object()
            if not job.in_terminal_state():
                job.status = Job.STOPPED
                job.save(update_fields=["status"])
            message = "Job has been stopped."
            runtime_jobs = self.get_runtime_job(job)
            if runtime_jobs and len(runtime_jobs) != 0:
                if request.data.get("service"):
                    service = QiskitRuntimeService(
                        **json.loads(request.data.get("service"), cls=json.JSONDecoder)[
                            "__value__"
                        ]
                    )
                    for runtime_job_entry in runtime_jobs:
                        jobinstance = service.job(runtime_job_entry.runtime_job)
                        if jobinstance:
                            try:
                                logger.info(
                                    "canceling [%s]", runtime_job_entry.runtime_job
                                )
                                jobinstance.cancel()
                            except RuntimeInvalidStateError:
                                logger.warning("cancel failed")

                            if jobinstance.session_id:
                                service._api_client.cancel_session(  # pylint: disable=protected-access
                                    jobinstance.session_id
                                )

            if job.compute_resource:
                if job.compute_resource.active:
                    job_handler = get_job_handler(job.compute_resource.host)
                    if job_handler is not None:
                        was_running = job_handler.stop(job.ray_job_id)
                        if not was_running:
                            message = "Job was already not running."
                    else:
                        logger.warning(
                            "Compute resource is not accessible %s",
                            job.compute_resource,
                        )
        return Response({"message": message})

    @action(methods=["POST"], detail=True)
    def add_runtimejob(
        self, request, pk=None
    ):  # pylint: disable=invalid-name,unused-argument
        """Add RuntimeJob to job"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.add_runtimejob", context=ctx):
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

    @action(methods=["GET"], detail=True)
    def list_runtimejob(
        self, request, pk=None
    ):  # pylint: disable=invalid-name,unused-argument
        """Add RuntimeJpb to job"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.stop", context=ctx):
            job = self.get_object()
            runtimejobs = RuntimeJob.objects.filter(job=job)
            ids = []
            for runtimejob in runtimejobs:
                ids.append(runtimejob.runtime_job)
        return Response(json.dumps(ids))
