"""
Django Rest framework views for api application:
    - Program ViewSet
    - Job ViewSet
    - KeycloakUsers ApiView

Version views inherit from the different views.
"""
import glob
import mimetypes
import os
import json
import logging
import time
from wsgiref.util import FileWrapper

import requests
from allauth.socialaccount.providers.keycloak.views import KeycloakOAuth2Adapter
from concurrency.exceptions import RecordModifiedError
from dj_rest_auth.registration.views import SocialLoginView
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import StreamingHttpResponse
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .models import Program, Job
from .ray import get_job_handler
from .schedule import save_program
from .serializers import JobSerializer, ExistingProgramSerializer, JobConfigSerializer
from .utils import build_env_variables, encrypt_env_vars

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
    def get_serializer_job_class():
        """
        This method returns Job serializer to be used in Program ViewSet.
        """

        return JobSerializer

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

        save_program(serializer=serializer, request=request)
        return Response(serializer.data)

    @action(methods=["POST"], detail=False)
    def run_existing(self, request):
        """Enqueues existing program."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.program.run_existing", context=ctx):
            serializer = ExistingProgramSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            title = serializer.data.get("title")
            program = (
                Program.objects.filter(title=title, author=request.user)
                .order_by("-created")
                .first()
            )

            if program is None:
                return Response(
                    {"message": f"program [{title}] was not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            jobconfig = None
            config_data = request.data.get("config")
            if config_data:
                config_serializer = JobConfigSerializer(data=json.loads(config_data))
                if not config_serializer.is_valid():
                    return Response(
                        config_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                jobconfig = config_serializer.save()

            job = Job(
                program=program,
                arguments=serializer.data.get("arguments"),
                author=request.user,
                status=Job.QUEUED,
                config=jobconfig,
            )
            #job.save()   !!!!!!!!!!!!

            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            env = encrypt_env_vars(
                build_env_variables(
                    request, job, json.dumps(serializer.data.get("arguments"))
                )
            )
            try:
                env["traceparent"] = carrier["traceparent"]
            except KeyError:
                pass
            job.env_vars = json.dumps(env)
            job.save()

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

            jobconfig = None
            config_data = request.data.get("config")
            if config_data:
                config_serializer = JobConfigSerializer(data=json.loads(config_data))
                if not config_serializer.is_valid():
                    return Response(
                        config_serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                jobconfig = config_serializer.save()

            program = save_program(serializer=serializer, request=request)

            job = Job(
                program=program,
                arguments=program.arguments,
                author=request.user,
                status=Job.QUEUED,
                config=jobconfig,
            )
            job.save()

            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            env = encrypt_env_vars(build_env_variables(request, job, program.arguments))
            try:
                env["traceparent"] = carrier["traceparent"]
            except KeyError:
                pass
            job.env_vars = json.dumps(env)
            job.save()

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

    @action(methods=["POST"], detail=True)
    def status(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """set status of a job."""
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.job.status", context=ctx):
            org = self.get_object()
            job_handler = get_job_handler(org.compute_resource.host)
            if job_handler:
                logs = job_handler.logs(org.ray_job_id)

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
                    job.status = request.data.get("status")
                    job.logs = logs
                    job.save()
                    saved = True
                    print("Setting status")
                    print(request.data.get("status"))
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
                    os.path.basename(path) for path in glob.glob(f"{user_dir}/*.tar")
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


class KeycloakLogin(SocialLoginView):
    """KeycloakLogin."""

    adapter_class = KeycloakOAuth2Adapter


class KeycloakUsersView(APIView):
    """KeycloakUsersView."""

    queryset = get_user_model().objects.all()
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        """Get application token.

        Request: /POST
        Body: {"username": ..., "password": ...}
        """
        keycloak_payload = {
            "grant_type": "password",
            "client_id": settings.SETTINGS_KEYCLOAK_CLIENT_ID,
            "client_secret": settings.SETTINGS_KEYCLOAK_CLIENT_SECRET,
            "scope": "openid",
        }
        keycloak_provider = settings.SOCIALACCOUNT_PROVIDERS.get("keycloak")
        if keycloak_provider is None:
            return Response(
                {
                    "message": "Oops. Provider was not configured correctly on a server side."
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        keycloak_url = (
            f"{keycloak_provider.get('KEYCLOAK_URL')}/realms/"
            f"{keycloak_provider.get('KEYCLOAK_REALM')}/"
            f"protocol/openid-connect/token/"
        )
        payload = {**keycloak_payload, **request.data}
        keycloak_response = requests.post(
            keycloak_url,
            data=payload,
            timeout=settings.SETTINGS_KEYCLOAK_REQUESTS_TIMEOUT,
        )
        if not keycloak_response.ok:
            return Response(
                {"message": keycloak_response.text}, status=status.HTTP_400_BAD_REQUEST
            )

        access_token = json.loads(keycloak_response.text).get("access_token")
        if settings.SITE_HOST is None:
            return Response(
                {
                    "message": "Oops. Application was not configured correctly on a server side."
                },
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )

        rest_auth_url = f"{settings.SITE_HOST}/dj-rest-auth/keycloak/"
        rest_auth_response = requests.post(
            rest_auth_url,
            json={"access_token": access_token},
            timeout=settings.SETTINGS_KEYCLOAK_REQUESTS_TIMEOUT,
        )

        if not rest_auth_response.ok:
            return Response(
                {"message": rest_auth_response.text}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(json.loads(rest_auth_response.text))
