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

from utils import sanitize_file_path
from api.models import Provider

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
