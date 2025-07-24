"""
Django Rest framework File views for api application:

Version views inherit from the different views.
"""
import logging
import os

from django.http import StreamingHttpResponse

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
    @action(methods=["GET"], detail=False)
    def download(self, request):
        """
        It returns a file from user paths:
            - username/
            - username/provider_name/function_title
        """
        username = request.user.username
        requested_file_name = sanitize_file_name(request.query_params.get("file", None))
        provider_name = sanitize_name(request.query_params.get("provider", None))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.USER_STORAGE

        if not all([requested_file_name, function_title]):
            return Response(
                {"message": "File name and Qiskit Function title are mandatory"},
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
        result = file_storage.get_file(file_name=requested_file_name)
        if result is None:
            return Response(
                {"message": "Requested file was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_wrapper, file_type, file_size = result
        response = StreamingHttpResponse(file_wrapper, content_type=file_type)
        response["Content-Length"] = file_size
        response["Content-Disposition"] = f"attachment; filename={requested_file_name}"
        return response

    @_trace
    @action(methods=["GET"], detail=False, url_path="provider/download")
    def provider_download(self, request):
        """
        It returns a file from provider path:
            - provider_name/function_title
        """
        username = request.user.username
        requested_file_name = sanitize_file_name(request.query_params.get("file", None))
        provider_name = sanitize_name(request.query_params.get("provider", None))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.PROVIDER_STORAGE

        if not all([requested_file_name, function_title, provider_name]):
            return Response(
                {
                    "message": "File name, Qiskit Function title and Provider name are mandatory"  # pylint: disable=line-too-long
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
        result = file_storage.get_file(file_name=requested_file_name)
        if result is None:
            return Response(
                {"message": "Requested file was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        file_wrapper, file_type, file_size = result
        response = StreamingHttpResponse(file_wrapper, content_type=file_type)
        response["Content-Length"] = file_size
        response["Content-Disposition"] = f"attachment; filename={requested_file_name}"
        return response

    @_trace
    @action(methods=["DELETE"], detail=False)
    def delete(self, request):
        """Deletes file uploaded or produced by the functions"""
        username = request.user.username
        file_name = sanitize_file_name(request.query_params.get("file", None))
        provider_name = sanitize_name(request.query_params.get("provider"))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.USER_STORAGE

        if not all([file_name, function_title]):
            return Response(
                {"message": "File name and Qiskit Function title are mandatory"},
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
        result = file_storage.remove_file(file_name=file_name)
        if not result:
            return Response(
                {"message": "Requested file was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"message": "Requested file was deleted."}, status=status.HTTP_200_OK
        )

    @_trace
    @action(methods=["DELETE"], detail=False, url_path="provider/delete")
    def provider_delete(self, request):
        """Deletes file uploaded or produced by the functions"""
        username = request.user.username
        file_name = sanitize_file_name(request.query_params.get("file"))
        provider_name = sanitize_name(request.query_params.get("provider"))
        function_title = sanitize_name(request.query_params.get("function", None))
        working_dir = WorkingDir.PROVIDER_STORAGE

        if not all([file_name, function_title, provider_name]):
            return Response(
                {"message": "File name and Qiskit Function title are mandatory"},
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
            error_message = f"Qiskit Function {provider_name}/{function_title} doesn't exist."  # pylint: disable=line-too-long
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
        result = file_storage.remove_file(file_name=file_name)
        if not result:
            return Response(
                {"message": "Requested file was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {"message": "Requested file was deleted."}, status=status.HTTP_200_OK
        )

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
