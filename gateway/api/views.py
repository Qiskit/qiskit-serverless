"""
Django Rest framework views for api application:
    - Program ViewSet
    - Job ViewSet

Version views inherit from the different views.
"""

import glob
import json
import logging
import mimetypes
import os
import time
from wsgiref.util import FileWrapper

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.http import StreamingHttpResponse
from django.db.models import Q
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from utils import sanitize_file_path

from .exceptions import InternalServerErrorException, ResourceNotFoundException
from .models import Program, Job, RuntimeJob, CatalogEntry
from .ray import get_job_handler
from .serializers import (
    JobSerializer,
    ExistingProgramSerializer,
    JobConfigSerializer,
    CatalogEntrySerializer,
    ToCatalogSerializer,
)
from .services import JobService, ProgramService, JobConfigService

logger = logging.getLogger("gateway")
resource = Resource(attributes={SERVICE_NAME: "QuantumServerless-Gateway"})
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


class ProgramViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Program ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "programs"

    @staticmethod
    def get_service_program_class():
        """
        This method returns Program service to be used in Program ViewSet.
        """

        return ProgramService

    @staticmethod
    def get_service_job_config_class():
        """
        This method return JobConfig service to be used in Program ViewSet.
        """

        return JobConfigService

    @staticmethod
    def get_service_job_class():
        """
        This method return Job service to be used in Program ViewSet.
        """

        return JobService

    @staticmethod
    def get_serializer_job_class():
        """
        This method returns Job serializer to be used in Program ViewSet.
        """

        return JobSerializer

    @staticmethod
    def get_serializer_existing_program_class():
        """
        This method returns Existign Program serializer to be used in Program ViewSet.
        """

        return ExistingProgramSerializer

    @staticmethod
    def get_serializer_job_config_class():
        """
        This method returns Job Config serializer to be used in Program ViewSet.
        """

        return JobConfigSerializer

    @staticmethod
    def get_serializer_catalog_entry_class():
        """
        This method returns add catalog entry serializer to be used in Program ViewSet.
        """

        return CatalogEntrySerializer

    @staticmethod
    def get_serializer_to_catalog_class():
        """
        This method returns to catalog serializer to be used in Program ViewSet.
        """

        return ToCatalogSerializer

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        # Allow unauthenticated users to read the swagger documentation
        if self.request.user is None or not self.request.user.is_authenticated:
            return Program.objects.none()
        return (
            Program.objects.all().filter(author=self.request.user).order_by("-created")
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """Uploads program."""
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        program_service = self.get_service_program_class()
        try:
            program = program_service.save(
                serializer=serializer,
                author=request.user,
                artifact=request.FILES.get("artifact"),
            )
        except InternalServerErrorException as exception:
            return Response(exception, exception.http_code)

        program_serializer = self.get_serializer(program)
        return Response(program_serializer.data)

    @action(methods=["POST"], detail=False)
    def run_existing(self, request):
        """Enqueues existing program."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.run_existing", context=ctx):
            serializer = self.get_serializer_existing_program_class()(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            author = request.user
            program = None
            program_service = self.get_service_program_class()
            try:
                title = serializer.data.get("title")
                program = program_service.find_one_by_title(title, author)
            except ResourceNotFoundException as exception:
                return Response(exception, exception.http_code)

            jobconfig = None
            config_data = request.data.get("config")
            if config_data:
                config_serializer = self.get_serializer_job_config_class()(
                    data=json.loads(config_data)
                )
                if not config_serializer.is_valid():
                    return Response(
                        config_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )
                try:
                    jobconfig = (
                        self.get_service_job_config_class().save_with_serializer(
                            config_serializer
                        )
                    )
                except InternalServerErrorException as exception:
                    return Response(exception, exception.http_code)

            job = None
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            arguments = serializer.data.get("arguments")
            token = ""
            if request.auth:
                token = request.auth.token.decode()
            try:
                job = self.get_service_job_class().save(
                    program=program,
                    arguments=arguments,
                    author=author,
                    jobconfig=jobconfig,
                    token=token,
                    carrier=carrier,
                )
            except InternalServerErrorException as exception:
                return Response(exception, exception.http_code)

            job_serializer = self.get_serializer_job_class()(job)
        return Response(job_serializer.data)

    @action(methods=["POST"], detail=False)
    def run(self, request):
        """Enqueues program for execution."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.run", context=ctx):
            serializer = self.get_serializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            author = request.user
            program = None
            program_service = self.get_service_program_class()
            try:
                program = program_service.save(
                    serializer=serializer,
                    author=author,
                    artifact=request.FILES.get("artifact"),
                )
            except InternalServerErrorException as exception:
                return Response(exception, exception.http_code)

            jobconfig = None
            config_data = request.data.get("config")
            if config_data:
                config_serializer = self.get_serializer_job_config_class()(
                    data=json.loads(config_data)
                )
                if not config_serializer.is_valid():
                    return Response(
                        config_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )
                try:
                    jobconfig = (
                        self.get_service_job_config_class().save_with_serializer(
                            config_serializer
                        )
                    )
                except InternalServerErrorException as exception:
                    return Response(exception, exception.http_code)

            job = None
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            arguments = serializer.data.get("arguments")
            token = request.auth.token.decode()
            try:
                job = self.get_service_job_class().save(
                    program=program,
                    arguments=arguments,
                    author=author,
                    jobconfig=jobconfig,
                    token=token,
                    carrier=carrier,
                )
            except InternalServerErrorException as exception:
                return Response(exception, exception.http_code)

            job_serializer = self.get_serializer_job_class()(job)
        return Response(job_serializer.data)

    @action(methods=["POST"], detail=True)
    def to_catalog(self, request, pk=None):  # pylint: disable=unused-argument
        """To catalog."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.to_catalog", context=ctx):
            serializer = self.get_serializer_to_catalog_class()(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            if not self.get_object().public:
                return Response(
                    "program must be public", status=status.HTTP_400_BAD_REQUEST
                )

            try:
                catalogentry = CatalogEntry(
                    title=serializer.data.get("title"),
                    description=serializer.data.get("description"),
                    tags=serializer.data.get("tags"),
                    status=serializer.data.get("status"),
                    program=self.get_object(),
                )
                catalogentry.save()
            except InternalServerErrorException as exception:
                return Response(exception, status=status.HTTP_400_BAD_REQUEST)
            catalog_entry_serializer = self.get_serializer_catalog_entry_class()(
                catalogentry
            )
        return Response(catalog_entry_serializer.data)


class JobViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Job ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        # Allow unauthenticated users to read the swagger documentation
        if self.request.user is None or not self.request.user.is_authenticated:
            return Job.objects.none()
        return (Job.objects.all()).filter(author=self.request.user).order_by("-created")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    def retrieve(self, request, pk=None):  # pylint: disable=arguments-differ
        queryset = Job.objects.all()
        job: Job = get_object_or_404(queryset, pk=pk)
        serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["POST"], detail=True)
    def result(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Save result of a job."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.result", context=ctx):
            saved = False
            attempts_left = 10
            while not saved:
                if attempts_left <= 0:
                    return Response(
                        {"error": "All attempts to save results failed."}, status=500
                    )

                attempts_left -= 1

                try:
                    job = self.get_object()
                    job.result = json.dumps(request.data.get("result"))
                    job.save()
                    saved = True
                except RecordModifiedError:
                    logger.warning(
                        "Job[%s] record has not been updated due to lock. "
                        "Retrying. Attempts left %s",
                        job.id,
                        attempts_left,
                    )
                    continue
                time.sleep(1)

            serializer = self.get_serializer(job)
        return Response(serializer.data)

    @action(methods=["GET"], detail=True)
    def logs(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Returns logs from job."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.logs", context=ctx):
            job = self.get_object()
            logs = job.logs
        return Response({"logs": logs})

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


class FilesViewSet(viewsets.ViewSet):
    """ViewSet for file operations handling.

    Note: only tar files are available for list and download
    """

    BASE_NAME = "files"

    def list(self, request):
        """List of available for user files."""
        files = []
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.list", context=ctx):
            user_dir = os.path.join(
                sanitize_file_path(settings.MEDIA_ROOT),
                sanitize_file_path(request.user.username),
            )
            if os.path.exists(user_dir):
                files = [
                    os.path.basename(path)
                    for path in glob.glob(f"{user_dir}/*.tar")
                    + glob.glob(f"{user_dir}/*.h5")
                ]
            else:
                logger.warning(
                    "Directory %s does not exist for %s.", user_dir, request.user
                )

        return Response({"results": files})

    @action(methods=["GET"], detail=False)
    def download(self, request):  # pylint: disable=invalid-name
        """Download selected file."""
        # default response for file not found, overwritten if file is found
        response = Response(
            {"message": "Requested file was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
            requested_file_name = request.query_params.get("file")
            if requested_file_name is not None:
                # look for file in user's folder
                filename = os.path.basename(requested_file_name)
                user_dir = os.path.join(
                    sanitize_file_path(settings.MEDIA_ROOT),
                    sanitize_file_path(request.user.username),
                )
                file_path = os.path.join(
                    sanitize_file_path(user_dir), sanitize_file_path(filename)
                )

                if os.path.exists(user_dir) and os.path.exists(file_path) and filename:
                    chunk_size = 8192
                    # note: we do not use with statements as Streaming response closing file itself.
                    response = StreamingHttpResponse(
                        FileWrapper(
                            open(  # pylint: disable=consider-using-with
                                file_path, "rb"
                            ),
                            chunk_size,
                        ),
                        content_type=mimetypes.guess_type(file_path)[0],
                    )
                    response["Content-Length"] = os.path.getsize(file_path)
                    response["Content-Disposition"] = f"attachment; filename={filename}"
            return response

    @action(methods=["DELETE"], detail=False)
    def delete(self, request):  # pylint: disable=invalid-name
        """Deletes file uploaded or produced by the programs,"""
        # default response for file not found, overwritten if file is found
        response = Response(
            {"message": "Requested file was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.delete", context=ctx):
            if request.data and "file" in request.data:
                # look for file in user's folder
                filename = os.path.basename(request.data["file"])
                user_dir = os.path.join(
                    sanitize_file_path(settings.MEDIA_ROOT),
                    sanitize_file_path(request.user.username),
                )
                file_path = os.path.join(
                    sanitize_file_path(user_dir), sanitize_file_path(filename)
                )

                if os.path.exists(user_dir) and os.path.exists(file_path) and filename:
                    os.remove(file_path)
                    response = Response(
                        {"message": "Requested file was deleted."},
                        status=status.HTTP_200_OK,
                    )
            return response

    @action(methods=["POST"], detail=False)
    def upload(self, request):  # pylint: disable=invalid-name
        """Upload selected file."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
            upload_file = request.FILES["file"]
            filename = os.path.basename(upload_file.name)
            user_dir = os.path.join(
                sanitize_file_path(settings.MEDIA_ROOT),
                sanitize_file_path(request.user.username),
            )
            file_path = os.path.join(
                sanitize_file_path(user_dir), sanitize_file_path(filename)
            )
            with open(file_path, "wb+") as destination:
                for chunk in upload_file.chunks():
                    destination.write(chunk)
            return Response({"message": file_path})
        return Response("server error", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RuntimeJobViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    RuntimeJob ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "runtime_jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return RuntimeJob.objects.all().filter(job__author=self.request.user)


class CatalogEntryViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    CatalogEntry ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "catalog_entries"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return CatalogEntry.objects.all()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()).filter(
            Q(program__author=self.request.user) | ~Q(status=CatalogEntry.PRIVATE)
        )
        title = request.query_params.get("title")
        description = request.query_params.get("description")
        tags = request.query_params.get("tags")
        if title:
            queryset = queryset.filter(title__contains=title)
        if description:
            queryset = queryset.filter(description__contains=description)
        if tags:
            queryset = queryset.filter(tags__contains=tags)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
