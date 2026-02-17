"""
Django Rest framework Program views for api application:

Version views inherit from the different views.
"""

import logging
import os

# pylint: disable=duplicate-code
from django.conf import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework.decorators import action
from rest_framework import viewsets, status
from rest_framework.response import Response

from api.decorators.trace_decorator import trace_decorator_factory
from api.domain.authentication.channel import Channel
from api.domain.exceptions.active_job_limit_exceeded_exception import (
    ActiveJobLimitExceeded,
)
from api.repositories.functions import FunctionRepository
from api.serializers import (
    JobConfigSerializer,
    RunJobSerializer,
    JobSerializer,
    RunProgramSerializer,
    UploadProgramSerializer,
)
from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Program, Job
from api.utils import sactive_jobs_limit_reached, anitize_name
from api.v1.endpoint_handle_exceptions import endpoint_handle_exceptions
from api.views.enums.type_filter import TypeFilter
from core.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Program, Job

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

_trace = trace_decorator_factory("program")


class ProgramViewSet(viewsets.GenericViewSet):
    """
    Program ViewSet configuration using GenericViewSet.
    """

    BASE_NAME = "programs"

    function_repository = FunctionRepository()

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

    @staticmethod
    def get_serializer_job(*args, **kwargs):
        """
        This method returns the job serializer
        """

        return JobSerializer(*args, **kwargs)

    def get_serializer_class(self):
        return self.serializer_class

    def get_object(self):
        logger.warning("ProgramViewSet.get_object not implemented")

    @_trace
    def list(self, request):
        """List programs:"""
        author = self.request.user
        type_filter = self.request.query_params.get("filter")

        if type_filter == TypeFilter.SERVERLESS:
            # Serverless filter only returns functions created by the author
            # with the next criterias:
            # - user is the author of the function and there is no provider
            functions = self.function_repository.get_user_functions(author)
        elif type_filter == TypeFilter.CATALOG:
            # Catalog filter only returns providers functions that user has access:
            # author has view permissions and the function has a provider assigned
            functions = self.function_repository.get_provider_functions_by_permission(
                author, permission_name=RUN_PROGRAM_PERMISSION
            )
        else:
            # If filter is not applied we return author and providers functions together
            functions = self.function_repository.get_functions_by_permission(
                author, permission_name=VIEW_PROGRAM_PERMISSION
            )

        serializer = self.get_serializer(functions, many=True)

        return Response(serializer.data)

    @_trace
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """Uploads a program:"""
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
            program = serializer.retrieve_private_function(title=title, author=author)

        if program is not None:
            logger.info("Program found. [%s] is going to be updated", title)
            serializer = self.get_serializer_upload_program(program, data=request.data)
            if not serializer.is_valid():
                logger.error(
                    "UploadProgramSerializer validation failed with program instance:\n %s",
                    serializer.errors,
                )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(author=author, title=title, provider=provider_name)

        logger.info("Return response with Program [%s]", title)
        return Response(serializer.data)

    @_trace
    @action(methods=["POST"], detail=False)
    @endpoint_handle_exceptions
    def run(self, request):  # pylint: disable=too-many-locals
        """Enqueues existing program."""
        serializer = self.get_serializer_run_program(data=request.data)
        if not serializer.is_valid():
            logger.error(
                "RunProgramSerializer validation failed:\n %s",
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        author = request.user
        # The sanitization should happen in the serializer
        # but it's here until we can refactor the /run end-point
        provider_name = sanitize_name(serializer.data.get("provider"))
        function_title = sanitize_name(serializer.data.get("title"))
        function = self.function_repository.get_function_by_permission(
            user=author,
            permission_name=RUN_PROGRAM_PERMISSION,
            function_title=function_title,
            provider_name=provider_name,
        )
        if function is None:
            logger.error("Qiskit Pattern [%s] was not found.", function_title)
            return Response(
                {"message": f"Qiskit Pattern [{function_title}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if function.disabled:
            error_message = (
                function.disabled_message
                if function.disabled_message
                else Program.DEFAULT_DISABLED_MESSAGE
            )
            return Response(
                {"message": error_message},
                status=status.HTTP_423_LOCKED,
            )

        jobconfig = None
        config_json = serializer.data.get("config")
        if config_json:
            logger.info("Configuration for [%s] was found.", function_title)
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
        channel = Channel.IBM_QUANTUM_PLATFORM
        token = ""
        instance = None
        if request.auth:
            channel = request.auth.channel
            token = request.auth.token.decode()
            instance = request.auth.instance
        job_data = {"arguments": arguments, "program": function.id}
        job_serializer = self.get_serializer_run_job(data=job_data)
        if not job_serializer.is_valid():
            logger.error(
                "RunJobSerializer validation failed:\n %s",
                serializer.errors,
            )
            return Response(job_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if active_jobs_limit_reached(author):
            logger.error(
                "The number of active jobs has reached the limit. The set limit is: %s",
                settings.LIMITS_ACTIVE_JOBS_PER_USER,
            )
            raise ActiveJobLimitExceeded()
        job = job_serializer.save(
            author=author,
            carrier=carrier,
            channel=channel,
            token=token,
            config=jobconfig,
            instance=instance,
        )
        logger.info("Returning Job [%s] created.", job.id)

        return Response(job_serializer.data)

    # is this intentionally not traced?
    @action(methods=["GET"], detail=False, url_path="get_by_title/(?P<title>[^/.]+)")
    def get_by_title(self, request, title):
        """Returns programs by title."""
        author = self.request.user
        function_title = sanitize_name(title)
        provider_name = sanitize_name(request.query_params.get("provider", None))

        serializer = self.get_serializer_upload_program(data=self.request.data)
        provider_name, function_title = serializer.get_provider_name_and_title(
            provider_name, function_title
        )

        if provider_name:
            function = self.function_repository.get_provider_function_by_permission(
                author=author,
                permission_name=VIEW_PROGRAM_PERMISSION,
                title=function_title,
                provider_name=provider_name,
            )
            if function is None:
                return Response(
                    {
                        "message": (
                            f"Program '{function_title}' for provider '{provider_name}' "
                            "was not found or you do not have permission to view it."
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            function = self.function_repository.get_user_function(
                author=author, title=function_title
            )
            if function is None:
                return Response(
                    {
                        "message": (
                            f"User program '{function_title}' was not found or "
                            "you do not have permission to view it."
                        )
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

        return Response(self.get_serializer(function).data)

    # This end-point is deprecated and we need to confirm if we can remove it
    @_trace
    @action(methods=["GET"], detail=True)
    def get_jobs(
        self, request, pk=None
    ):  # pylint: disable=invalid-name,unused-argument
        """Returns jobs of the program."""
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
        serializer = self.get_serializer_job(jobs, many=True)
        return Response(serializer.data)
