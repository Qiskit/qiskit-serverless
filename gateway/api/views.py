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

from .exceptions import InternalServerErrorException, ResourceNotFoundException
from .models import Program, Job
from .ray import get_job_handler
from .serializers import JobSerializer, ExistingProgramSerializer, JobConfigSerializer
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

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
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
            token = request.auth.token.decode()
            try:
                job = self.get_service_job_class().save(
                    program=program,
                    arguments=arguments,
                    author=author,
                    status=Job.QUEUED,
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
                    status=Job.QUEUED,
                    jobconfig=jobconfig,
                    token=token,
                    carrier=carrier,
                )
            except InternalServerErrorException as exception:
                return Response(exception, exception.http_code)

            job_serializer = self.get_serializer_job_class()(job)
        return Response(job_serializer.data)


class JobViewSet(viewsets.ModelViewSet):  # pylint: disable=too-many-ancestors
    """
    Job ViewSet configuration using ModelViewSet.
    """

    BASE_NAME = "jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return Job.objects.all().filter(author=self.request.user).order_by("-created")

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
            user_dir = os.path.join(settings.MEDIA_ROOT, request.user.username)
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
                user_dir = os.path.join(settings.MEDIA_ROOT, request.user.username)
                file_path = os.path.join(user_dir, filename)

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
                user_dir = os.path.join(settings.MEDIA_ROOT, request.user.username)
                file_path = os.path.join(user_dir, filename)

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
            user_dir = os.path.join(settings.MEDIA_ROOT, request.user.username)
            file_path = os.path.join(user_dir, filename)
            with open(file_path, "wb+") as destination:
                for chunk in upload_file.chunks():
                    destination.write(chunk)
            return Response({"message": file_path})
        return Response("server error", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
