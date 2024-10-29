"""
Django Rest framework File views for api application:

Version views inherit from the different views.
"""
import glob
import logging
import mimetypes
import os
from wsgiref.util import FileWrapper

from django.conf import settings
from django.http import StreamingHttpResponse

# pylint: disable=duplicate-code
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.services.file_storage import PROVIDER_STORAGE, USER_STORAGE, FileStorage
from api.utils import sanitize_name
from api.models import Provider, Program
from utils import sanitize_file_path

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

    def user_has_provider_access(self, user, provider_name: str) -> bool:
        """
        This method returns True or False if the user has access to the provider or not.
        """

        provider = Provider.objects.filter(name=provider_name).first()
        if provider is None:
            logger.error("Provider [%s] does not exist.", provider_name)
            return False

        user_groups = user.groups.all()
        admin_groups = provider.admin_groups.all()
        has_access = any(group in admin_groups for group in user_groups)
        if not has_access:
            logger.error(
                "User [%s] has no access to provider [%s].", user.id, provider_name
            )
        return has_access

    def user_has_access_to_provider_function(
        self, user, provider_name: str, function_title: str
    ) -> bool:
        """
        This method returns True or False if the user has access to the provider function.
        """

        provider = Provider.objects.filter(name=provider_name).first()
        if provider is None:
            logger.error("Provider [%s] does not exist.", provider_name)
            return False

        function = Program.objects.filter(
            title=function_title, provider=provider
        ).first()
        if function is None:
            logger.error(
                "Function [%s/%s] does not exist.", provider_name, function_title
            )
            return False

        instances = function.instances.all()
        user_groups = user.groups.all()
        has_access = any(group in instances for group in user_groups)
        if not has_access:
            logger.error(
                "User [%s] has no access to function [%s/%s].",
                user.id,
                provider_name,
                function_title,
            )
        return has_access

    def list(self, request):
        """
        It returns a list with the names of available files.
        Depending of the working_dir:
            - "user": it will look under its username or username/provider_name/function_title
            - "provider": it will look under provider_name/function_title
        """

        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.list", context=ctx):
            username = request.user.username
            provider_name = sanitize_name(request.query_params.get("provider"))
            function_title = sanitize_name(request.query_params.get("function"))
            working_dir = request.query_params.get(
                "working_dir"
            )  # It can be "user" or "provider"

            if working_dir == USER_STORAGE:
                if provider_name:
                    if not self.user_has_access_to_provider_function(
                        request.user, provider_name, function_title
                    ):
                        return Response(
                            {
                                "message": "You don't have access to this Qiskit Function."
                            },
                            status=status.HTTP_403_FORBIDDEN,
                        )
            elif working_dir == PROVIDER_STORAGE:
                if not self.user_has_provider_access(request.user, provider_name):
                    return Response(
                        {"message": "You don't have access to this provider."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            else:
                return Response(
                    {
                        "message": "Working directory is not correct. Must be from a user or from a provider."  # pylint: disable=line-too-long
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            file_storage = FileStorage(
                username=username,
                working_dir=working_dir,
                function_title=function_title,
                provider_name=provider_name,
            )

            if os.path.exists(file_storage.file_path):
                files = [
                    os.path.basename(path)
                    for path in glob.glob(f"{file_storage.file_path}/*.tar")
                    + glob.glob(f"{file_storage.file_path}/*.h5")
                ]
            else:
                logger.warning(
                    "Directory %s does not exist for %s.",
                    file_storage.file_path,
                    request.user,
                )
                files = []
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
