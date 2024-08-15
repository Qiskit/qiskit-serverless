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
from typing import Optional
from wsgiref.util import FileWrapper

from concurrency.exceptions import RecordModifiedError
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.http import StreamingHttpResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from qiskit_ibm_runtime import RuntimeInvalidStateError, QiskitRuntimeService
from utils import sanitize_file_path

from .models import (
    VIEW_PROGRAM_PERMISSION,
    RUN_PROGRAM_PERMISSION,
    Program,
    Job,
    RuntimeJob,
    Provider,
)
from .ray import get_job_handler
from .serializers import (
    JobConfigSerializer,
    RunJobSerializer,
    RunProgramSerializer,
    UploadProgramSerializer,
    RetrieveCatalogSerializer,
)

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


class ProgramViewSet(viewsets.GenericViewSet):
    """
    Program ViewSet configuration using GenericViewSet.
    """

    BASE_NAME = "programs"

    @staticmethod
    def get_serializer_job_config(*args, **kwargs):
        """
        This method returns Job Config serializer to be used in Program ViewSet.
        """

        return JobConfigSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_upload_program(*args, **kwargs):
        """
        This method returns the program serializer for the upload end-point
        """

        return UploadProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_program(*args, **kwargs):
        """
        This method returns the program serializer for the run end-point
        """

        return RunProgramSerializer(*args, **kwargs)

    @staticmethod
    def get_serializer_run_job(*args, **kwargs):
        """
        This method returns the job serializer for the run end-point
        """

        return RunJobSerializer(*args, **kwargs)

    def get_serializer_class(self):
        return self.serializer_class

    def get_object(self):
        logger.warning("ProgramViewSet.get_object not implemented")

    def get_queryset(self):
        author = self.request.user
        title = self.request.query_params.get("title")
        provider_name = self.request.query_params.get("provider")

        author_programs = self._get_program_queryset_for_title_and_provider(
            author=author, title=title, provider_name=provider_name
        ).distinct()

        author_programs_count = author_programs.count()
        logger.info(
            "ProgramViewSet get author[%s] programs[%s]",
            author.id,
            author_programs_count,
        )

        return author_programs

    def get_run_queryset(self):
        """get run queryset"""
        author = self.request.user

        logger.info("ProgramViewSet get run_program permission")
        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

        # Groups logic
        user_criteria = Q(user=author)
        run_permission_criteria = Q(permissions=run_program_permission)
        author_groups_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria
        )
        author_groups_with_run_permissions_count = (
            author_groups_with_run_permissions.count()
        )
        logger.info(
            "ProgramViewSet get author[%s] groups [%s]",
            author.id,
            author_groups_with_run_permissions_count,
        )

        # Programs logic
        author_criteria = Q(author=author)
        author_groups_with_run_permissions_criteria = Q(
            instances__in=author_groups_with_run_permissions
        )
        author_programs = Program.objects.filter(
            author_criteria | author_groups_with_run_permissions_criteria
        ).distinct()
        author_programs_count = author_programs.count()
        logger.info(
            "ProgramViewSet get author[%s] programs[%s]",
            author.id,
            author_programs_count,
        )

        return author_programs

    def list(self, request):
        """List programs:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.list", context=ctx):
            serializer = self.get_serializer(self.get_queryset(), many=True)

        return Response(serializer.data)

    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """Uploads a program:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.upload", context=ctx):
            serializer = self.get_serializer_upload_program(data=request.data)
            if not serializer.is_valid():
                logger.error(
                    "UploadProgramSerializer validation failed:\n %s",
                    serializer.errors,
                )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            title = serializer.validated_data.get("title")
            request_provider = serializer.validated_data.get("provider", None)
            author = request.user
            provider_name, title = serializer.get_provider_name_and_title(
                request_provider, title
            )

            if provider_name:
                user_has_access = serializer.check_provider_access(
                    provider_name=provider_name, author=author
                )
                if not user_has_access:
                    # For security we just return a 404 not a 401
                    return Response(
                        {"message": f"Provider [{provider_name}] was not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                program = serializer.retrieve_provider_function(
                    title=title, provider_name=provider_name
                )
            else:
                program = serializer.retrieve_private_function(
                    title=title, author=author
                )

            if program is not None:
                logger.info("Program found. [%s] is going to be updated", title)
                serializer = self.get_serializer_upload_program(
                    program, data=request.data
                )
                if not serializer.is_valid():
                    logger.error(
                        "UploadProgramSerializer validation failed with program instance:\n %s",
                        serializer.errors,
                    )
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )
            serializer.save(author=author, title=title, provider=provider_name)

            logger.info("Return response with Program [%s]", title)
            return Response(serializer.data)

    @action(methods=["POST"], detail=False)
    def run(self, request):
        """Enqueues existing program."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.run", context=ctx):
            serializer = self.get_serializer_run_program(data=request.data)
            if not serializer.is_valid():
                logger.error(
                    "RunExistingProgramSerializer validation failed:\n %s",
                    serializer.errors,
                )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            author_program = self.get_run_queryset()
            author = request.user
            title = serializer.data.get("title")
            program = author_program.filter(title=title).first()
            if program is None:
                logger.error("Qiskit Pattern [%s] was not found.", title)
                return Response(
                    {"message": f"Qiskit Pattern [{title}] was not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            jobconfig = None
            config_json = serializer.data.get("config")
            if config_json:
                logger.info("Configuration for [%s] was found.", title)
                job_config_serializer = self.get_serializer_job_config(data=config_json)
                if not job_config_serializer.is_valid():
                    logger.error(
                        "JobConfigSerializer validation failed:\n %s",
                        serializer.errors,
                    )
                    return Response(
                        job_config_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )
                jobconfig = job_config_serializer.save()
                logger.info("JobConfig [%s] created.", jobconfig.id)

            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            arguments = serializer.data.get("arguments")
            token = ""
            if request.auth:
                token = request.auth.token.decode()
            job_data = {"arguments": arguments, "program": program.id}
            job_serializer = self.get_serializer_run_job(data=job_data)
            if not job_serializer.is_valid():
                logger.error(
                    "RunJobSerializer validation failed:\n %s",
                    serializer.errors,
                )
                return Response(
                    job_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                )
            job = job_serializer.save(
                author=author, carrier=carrier, token=token, config=jobconfig
            )
            logger.info("Returning Job [%s] created.", job.id)

        return Response(job_serializer.data)

    @action(methods=["GET"], detail=False, url_path="get_by_title/(?P<title>[^/.]+)")
    def get_by_title(self, request, title):
        """Returns programs by title."""
        author = self.request.user
        provider_name = self.request.query_params.get("provider")

        result_program = self._get_program_queryset_for_title_and_provider(
            author=author, title=title, provider_name=provider_name
        ).first()

        if result_program:
            return Response(self.get_serializer(result_program).data)

        return Response(status=404)

    def _get_program_queryset_for_title_and_provider(
        self, author, title: str, provider_name: Optional[str]
    ):
        """Returns queryset for program for gived request, title and provider."""
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        # Groups logic
        user_criteria = Q(user=author)
        view_permission_criteria = Q(permissions=view_program_permission)
        author_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )
        author_groups_with_view_permissions_count = (
            author_groups_with_view_permissions.count()
        )
        logger.info(
            "ProgramViewSet get author[%s] groups [%s]",
            author.id,
            author_groups_with_view_permissions_count,
        )

        # Programs logic
        author_criteria = Q(author=author)
        author_groups_with_view_permissions_criteria = Q(
            instances__in=author_groups_with_view_permissions
        )
        if title:
            serializer = self.get_serializer_upload_program(data=self.request.data)
            provider_name, title = serializer.get_provider_name_and_title(
                provider_name, title
            )
            title_criteria = Q(title=title)
            if provider_name:
                title_criteria = Q(title=title, provider__name=provider_name)
            result_queryset = Program.objects.filter(
                (author_criteria | author_groups_with_view_permissions_criteria)
                & title_criteria
            )
        else:
            result_queryset = Program.objects.filter(
                author_criteria | author_groups_with_view_permissions_criteria
            )

        return result_queryset

    @action(methods=["GET"], detail=True)
    def get_jobs(
        self, request, pk=None
    ):  # pylint: disable=invalid-name,unused-argument
        """Returns jobs of the program."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.get_jobs", context=ctx):
            program = Program.objects.filter(id=pk).first()
            if not program:
                return Response(
                    {"message": f"program [{pk}] was not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user_is_provider = False
            if program.provider:
                admin_groups = program.provider.admin_groups.all()
                user_groups = request.user.groups.all()
                user_is_provider = any(group in admin_groups for group in user_groups)

            if user_is_provider:
                jobs = Job.objects.filter(program=program)
            else:
                jobs = Job.objects.filter(program=program, author=request.user)
            return Response(
                list(
                    jobs.values(
                        "status", "result", "id", "created", "version", "arguments"
                    )
                )
            )


class JobViewSet(viewsets.GenericViewSet):
    """
    Job ViewSet configuration using GenericViewSet.
    """

    BASE_NAME = "jobs"

    def get_serializer_class(self):
        return self.serializer_class

    def get_queryset(self):
        return Job.objects.filter(author=self.request.user).order_by("-created")

    def retrieve(self, request, pk=None):  # pylint: disable=unused-argument
        """Get job:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.retrieve", context=ctx):
            instance = self.get_object()
            serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def list(self, request):
        """List jobs:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.list", context=ctx):
            queryset = self.filter_queryset(self.get_queryset())

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.get_serializer(page, many=True)
                return self.get_paginated_response(serializer.data)

            serializer = self.get_serializer(queryset, many=True)
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


class FilesViewSet(viewsets.ViewSet):
    """ViewSet for file operations handling.

    Note: only tar files are available for list and download
    """

    BASE_NAME = "files"

    def list_user_providers(self, user):
        """list provider names that the user in"""
        provider_list = []
        providers = Provider.objects.all()
        for instance in providers:
            user_groups = user.groups.all()
            admin_groups = instance.admin_groups.all()
            provider_found = any(group in admin_groups for group in user_groups)
            if provider_found:
                provider_list.append(instance.name)
        return provider_list

    def check_user_has_provider(self, user, provider_name):
        """check if user has the provider"""
        return provider_name in self.list_user_providers(user)

    def list(self, request):
        """List of available for user files."""
        response = Response(
            {"message": "Requested file was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
        files = []
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.list", context=ctx):
            user_dir = request.user.username
            provider_name = request.query_params.get("provider")
            if provider_name is not None:
                if self.check_user_has_provider(request.user, provider_name):
                    user_dir = provider_name
                else:
                    return response
            user_dir = os.path.join(
                sanitize_file_path(settings.MEDIA_ROOT),
                sanitize_file_path(user_dir),
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
            provider_name = request.query_params.get("provider")
            if requested_file_name is not None:
                user_dir = request.user.username
                if provider_name is not None:
                    if self.check_user_has_provider(request.user, provider_name):
                        user_dir = provider_name
                    else:
                        return response
                # look for file in user's folder
                filename = os.path.basename(requested_file_name)
                user_dir = os.path.join(
                    sanitize_file_path(settings.MEDIA_ROOT),
                    sanitize_file_path(user_dir),
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
                provider_name = request.data.get("provider")
                user_dir = request.user.username
                if provider_name is not None:
                    if self.check_user_has_provider(request.user, provider_name):
                        user_dir = provider_name
                    else:
                        return response
                user_dir = os.path.join(
                    sanitize_file_path(settings.MEDIA_ROOT),
                    sanitize_file_path(user_dir),
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
        response = Response(
            {"message": "Requested file was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
            upload_file = request.FILES["file"]
            filename = os.path.basename(upload_file.name)
            user_dir = request.user.username
            if request.data and "provider" in request.data:
                provider_name = request.data["provider"]
                if provider_name is not None:
                    if self.check_user_has_provider(request.user, provider_name):
                        user_dir = provider_name
                    else:
                        return response
            user_dir = os.path.join(
                sanitize_file_path(settings.MEDIA_ROOT),
                sanitize_file_path(user_dir),
            )
            file_path = os.path.join(
                sanitize_file_path(user_dir), sanitize_file_path(filename)
            )
            with open(file_path, "wb+") as destination:
                for chunk in upload_file.chunks():
                    destination.write(chunk)
                    return Response({"message": file_path})
        return Response("server error", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CatalogViewSet(viewsets.GenericViewSet):
    """ViewSet to handle requests from IQP for the catalog page.

    This ViewSet contains public end-points to retrieve information.
    """

    BASE_NAME = "catalog"
    PUBLIC_GROUP_NAME = "public"  # "ibm-q/open/main"

    @staticmethod
    def get_serializer_retrieve_catalog(*args, **kwargs):
        """
        This method returns Retrieve Catalog serializer to be used in Catalog ViewSet.
        """

        return RetrieveCatalogSerializer(*args, **kwargs)

    def get_queryset(self):
        # try:
        public_group = Group.objects.get(name=self.PUBLIC_GROUP_NAME)
        # except:
        return Program.objects.filter(instances=public_group).distinct()

    def get_retrieve_queryset(self, pk):
        # try:
        public_group = Group.objects.get(name=self.PUBLIC_GROUP_NAME)
        # except:
        return Program.objects.filter(id=pk, instances=public_group).first()

    def list(self, request):
        """List programs:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.catalog.list", context=ctx):
            author = None
            if request.user.is_authenticated:
                author = request.user
            serializer = self.get_serializer(
                self.get_queryset(), context={"author": author}, many=True
            )
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        """Get program:"""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.catalog.retrieve", context=ctx):
            instance = self.get_retrieve_queryset(pk)
            if instance is None:
                return Response(
                    {"message": "Qiskit Function not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            author = None
            if request.user.is_authenticated:
                author = request.user
            serializer = self.get_serializer_retrieve_catalog(
                instance, context={"author": author}
            )
        return Response(serializer.data)
