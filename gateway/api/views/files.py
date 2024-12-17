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
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.services.file_storage import FileStorage, WorkingDir
from api.utils import sanitize_file_name, sanitize_name
from api.models import Provider, Program

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
    """
    ViewSet for file operations handling.
    """

    BASE_NAME = "files"

    # Functions methods, these will be migrated to a Repository class
    def get_function(
        self, user, function_title: str, provider_name: str | None
    ) -> None:
        """
        This method returns the specified function.

        Args:
            user: Django user of the function that wants to get it
            function_title (str): title of the function
            provider_name (str | None): name of the provider owner of the function

        Returns:
            Program | None: returns the function if it exists
        """

        if not provider_name:
            return self.get_user_function(user=user, function_title=function_title)

        function = self.get_provider_function(
            provider_name=provider_name, function_title=function_title
        )
        if function and self.user_has_access_to_provider_function(
            user=user, function=function
        ):
            return function

        return None

    def get_user_function(self, user, function_title: str) -> Program | None:
        """
        This method returns the specified function.

        Args:
            user: Django user to identify the author of the function
            function_title (str): title of the function

        Returns:
            Program | None: returns the function if it exists
        """

        function = Program.objects.filter(title=function_title, author=user).first()
        if function is None:
            logger.error(
                "Function [%s] does not exist for the author [%s]",
                function_title,
                user.id,
            )
            return None
        return function

    def get_provider_function(
        self, provider_name: str, function_title: str
    ) -> Program | None:
        """
        This method returns the specified function from a provider.

        Args:
            provider_name (str): name of the provider
            function_title (str): title of the function

        Returns:
            Program | None: returns the function if it exists
        """

        provider = Provider.objects.filter(name=provider_name).first()
        if provider is None:
            logger.error("Provider [%s] does not exist.", provider_name)
            return None

        function = Program.objects.filter(
            title=function_title, provider=provider
        ).first()
        if function is None:
            logger.error(
                "Function [%s/%s] does not exist.", provider_name, function_title
            )
            return None
        return function

    def user_has_access_to_provider_function(self, user, function: Program) -> bool:
        """
        This method returns True or False if the user has access to the provider function.

        Args:
            user: Django user that is being checked
            function (Program): the Qiskit Function that is going to be checked

        Returns:
            bool: boolean value that verifies if the user has access or not to the function
        """

        instances = function.instances.all()
        user_groups = user.groups.all()
        has_access = any(group in instances for group in user_groups)
        if not has_access:
            logger.error(
                "User [%s] has no access to function [%s/%s].",
                user.id,
                function.provider.name,
                function.title,
            )
        return has_access

    # Provider methods, these will be migrated to a Repository class
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

    def list(self, request):
        """
        It returns a list with the names of available files for the user directory:
            it will look under its username or username/provider_name/function_title
        """

        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.list", context=ctx):
            username = request.user.username
            provider_name = sanitize_name(request.query_params.get("provider", None))
            function_title = sanitize_name(request.query_params.get("function", None))
            working_dir = WorkingDir.USER_STORAGE

            if function_title is None:
                return Response(
                    {"message": "Qiskit Function title is mandatory"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            function = self.get_function(
                user=request.user,
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
            files = file_storage.get_files()

        return Response({"results": files})

    @action(methods=["GET"], detail=False, url_path="provider")
    def provider_list(self, request):
        """
        It returns a list with the names of available files for the provider working directory:
            provider_name/function_title
        """
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.provider_list", context=ctx):
            username = request.user.username
            provider_name = sanitize_name(request.query_params.get("provider"))
            function_title = sanitize_name(request.query_params.get("function"))
            working_dir = WorkingDir.PROVIDER_STORAGE

            if function_title is None or provider_name is None:
                return Response(
                    {
                        "message": "File name, Qiskit Function title and Provider name are mandatory"  # pylint: disable=line-too-long
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not self.user_has_provider_access(request.user, provider_name):
                return Response(
                    {"message": f"Provider {provider_name} doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            function = self.get_function(
                user=request.user,
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
            files = file_storage.get_files()

        return Response({"results": files})

    @action(methods=["GET"], detail=False)
    def download(self, request):
        """
        It returns a file from user paths:
            - username/
            - username/provider_name/function_title
        """
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
            username = request.user.username
            requested_file_name = sanitize_file_name(
                request.query_params.get("file", None)
            )
            provider_name = sanitize_name(request.query_params.get("provider", None))
            function_title = sanitize_name(request.query_params.get("function", None))
            working_dir = WorkingDir.USER_STORAGE

            if not all([requested_file_name, function_title]):
                return Response(
                    {"message": "File name and Qiskit Function title are mandatory"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            function = self.get_function(
                user=request.user,
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
            response[
                "Content-Disposition"
            ] = f"attachment; filename={requested_file_name}"
            return response

    @action(methods=["GET"], detail=False, url_path="provider/download")
    def provider_download(self, request):
        """
        It returns a file from provider path:
            - provider_name/function_title
        """
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span(
            "gateway.files.provider_download", context=ctx
        ):
            username = request.user.username
            requested_file_name = sanitize_file_name(
                request.query_params.get("file", None)
            )
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

            if not self.user_has_provider_access(request.user, provider_name):
                return Response(
                    {"message": f"Provider {provider_name} doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            function = self.get_function(
                user=request.user,
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
            response[
                "Content-Disposition"
            ] = f"attachment; filename={requested_file_name}"
            return response

    @action(methods=["DELETE"], detail=False)
    def delete(self, request):
        """Deletes file uploaded or produced by the programs,"""
        # default response for file not found, overwritten if file is found
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.delete", context=ctx):
            # look for file in user's folder
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

            function = self.get_function(
                user=request.user,
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

    @action(methods=["DELETE"], detail=False, url_path="provider/delete")
    def provider_delete(self, request):
        """Deletes file uploaded or produced by the programs,"""
        # default response for file not found, overwritten if file is found
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.delete", context=ctx):
            # look for file in user's folder
            username = request.user.username
            file_name = sanitize_file_name(request.query_params.get("file"))
            provider_name = sanitize_name(request.query_params.get("provider"))
            function_title = sanitize_name(request.query_params.get("function", None))
            working_dir = WorkingDir.USER_STORAGE

            if not all([file_name, function_title, provider_name]):
                return Response(
                    {"message": "File name and Qiskit Function title are mandatory"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not self.user_has_provider_access(request.user, provider_name):
                return Response(
                    {"message": f"Provider {provider_name} doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            function = self.get_function(
                user=request.user,
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

    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """
        It upload a file to a specific user paths:
            - username/
            - username/provider_name/function_title
        """
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
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

            function = self.get_function(
                user=request.user,
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

    @action(methods=["POST"], detail=False, url_path="provider/upload")
    def provider_upload(self, request):
        """
        It upload a file to a specific user paths:
            - provider_name/function_title
        """
        tracer = trace.get_tracer("gateway.tracer")
        ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
        with tracer.start_as_current_span("gateway.files.download", context=ctx):
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

            if not self.user_has_provider_access(request.user, provider_name):
                return Response(
                    {"message": f"Provider {provider_name} doesn't exist."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            function = self.get_function(
                user=request.user,
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
