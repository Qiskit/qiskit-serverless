"""
Django Rest framework File views for api application:

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
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.access_policies.providers import ProviderAccessPolicy
from api.models import RUN_PROGRAM_PERMISSION
from api.repositories.functions import FunctionRepository
from api.repositories.providers import ProviderRepository
from api.services.file_storage import FileStorage, WorkingDir
from api.utils import sanitize_file_name, sanitize_name
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

_trace = trace_decorator_factory("files")


class FilesViewSet(viewsets.ViewSet):
    """
    ViewSet for file operations handling.
    """

    BASE_NAME = "files"

    function_repository = FunctionRepository()
    provider_repository = ProviderRepository()

    @_trace
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """
        It upload a file to a specific user paths:
            - username/
            - username/provider_name/function_title
        """
        username = request.user.username
        upload_file = request.FILES["file"]
        file_name = sanitize_file_name(upload_file.name)
        provider_name = sanitize_name(request.query_params.get("provider", None))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.USER_STORAGE

        if not all([file_name, function_title]):
            return Response(
                {"message": "A file and Qiskit Function title are mandatory"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        function = self.function_repository.get_function_by_permission(
            user=request.user,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )
        if not function:
            if provider_name:
                error_message = f"Qiskit Function {provider_name}/{function_title} doesn't exist."  # pylint: disable=line-too-long
            else:
                error_message = f"Qiskit Function {function_title} doesn't exist."
            return Response(
                {"message": error_message},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_storage = FileStorage(
            username=username,
            working_dir=working_dir,
            function_title=function_title,
            provider_name=provider_name,
        )
        result = file_storage.upload_file(file=upload_file)

        return Response({"message": result})

    @_trace
    @action(methods=["POST"], detail=False, url_path="provider/upload")
    def provider_upload(self, request):
        """
        It upload a file to a specific user paths:
            - provider_name/function_title
        """
        username = request.user.username
        upload_file = request.FILES["file"]
        file_name = sanitize_file_name(upload_file.name)
        provider_name = sanitize_name(request.query_params.get("provider", None))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.PROVIDER_STORAGE

        if not all([file_name, function_title, provider_name]):
            return Response(
                {
                    "message": "The file, Qiskit Function title and Provider name are mandatory"  # pylint: disable=line-too-long
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider = self.provider_repository.get_provider_by_name(name=provider_name)
        if provider is None:
            return Response(
                {"message": f"Provider {provider_name} doesn't exist."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not ProviderAccessPolicy.can_access(user=request.user, provider=provider):
            return Response(
                {"message": f"Provider {provider_name} doesn't exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        function = self.function_repository.get_function_by_permission(
            user=request.user,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )
        if not function:
            return Response(
                {
                    "message": f"Qiskit Function {provider_name}/{function_title} doesn't exist."  # pylint: disable=line-too-long
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        file_storage = FileStorage(
            username=username,
            working_dir=working_dir,
            function_title=function_title,
            provider_name=provider_name,
        )
        result = file_storage.upload_file(file=upload_file)

        return Response({"message": result})
