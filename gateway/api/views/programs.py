"""
Django Rest framework Program views for api application:

Version views inherit from the different views.
"""

import logging
import os
import re

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

from typing import cast

from api.access_policies.providers import ProviderAccessPolicy
from api.decorators.trace_decorator import trace_decorator_factory
from api.domain.authentication.channel import Channel
from api.domain.authorization.function_access_result import FunctionAccessResult
from api.domain.exceptions.active_job_limit_exceeded_exception import (
    ActiveJobLimitExceeded,
)

from api.serializers import (
    JobConfigSerializer,
    RunJobSerializer,
    JobSerializer,
    RunProgramSerializer,
    UploadProgramSerializer,
)
from api.utils import active_jobs_limit_reached, sanitize_name
from api.v1.exception_handler import endpoint_handle_exceptions
from core.enums.type_filter import TypeFilter
from core.models import (
    PLATFORM_PERMISSION_READ,
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    VIEW_PROGRAM_PERMISSION,
    Job,
    Provider,
)
from core.models import Program as Function

# pylint: disable=duplicate-code
logger = logging.getLogger("api.api.views.programs")
resource = Resource(attributes={SERVICE_NAME: "QiskitServerless-Gateway"})
provider = TracerProvider(resource=resource)
otel_exporter = BatchSpanProcessor(
    OTLPSpanExporter(
        endpoint=os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"),
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
        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-list] user_id=%s filter=%s accessible_functions=%s",
            author.id,
            type_filter,
            accessible_functions,
        )

        if type_filter == TypeFilter.SERVERLESS:
            # Serverless filter only returns functions created by the author
            # with the next criterias:
            # - user is the author of the function and there is no provider
            functions = Function.objects.user_functions(author)
        elif accessible_functions.use_legacy_authorization:
            if type_filter == TypeFilter.CATALOG:
                # Catalog filter only returns providers functions that user has access:
                # author has view permissions and the function has a provider assigned
                functions = Function.objects.provider_functions().with_permission(
                    author, legacy_permission_name=RUN_PROGRAM_PERMISSION
                )
            else:
                # If filter is not applied we return author and providers functions together
                functions = Function.objects.with_permission(author, legacy_permission_name=VIEW_PROGRAM_PERMISSION)
        else:
            # Runtime API /functions determines the accessible_functions
            if type_filter == TypeFilter.CATALOG:
                # Catalog filter only returns provider functions that user has access:
                # author has run permissions and the function has a provider assigned
                functions = Function.objects.provider_functions().with_permission(
                    author,
                    legacy_permission_name=RUN_PROGRAM_PERMISSION,
                    filter_function_names=accessible_functions.get_functions_by_provider(PLATFORM_PERMISSION_RUN),
                )
            else:
                # If filter is not applied we return author + providers functions together
                functions = Function.objects.with_permission(
                    author,
                    legacy_permission_name=VIEW_PROGRAM_PERMISSION,
                    filter_function_names=accessible_functions.get_functions_by_provider(PLATFORM_PERMISSION_READ),
                )

        serializer = self.get_serializer(list(functions), many=True)
        logger.info(
            "[programs-list] user_id=%s filter=%s | Functions listed ok",
            author.id,
            type_filter,
        )
        return Response(serializer.data)

    @_trace
    @action(methods=["POST"], detail=False)
    def upload(self, request):
        """Uploads a program:"""
        serializer = self.get_serializer_upload_program(data=request.data)
        if not serializer.is_valid():
            logger.error(
                "[programs-upload] user_id=%s validation failed: %s",
                request.user.id,
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        title = serializer.validated_data.get("title")
        request_provider = serializer.validated_data.get("provider", None)
        author = request.user
        provider_name, title = serializer.get_provider_name_and_title(request_provider, title)

        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-upload] user_id=%s program=%s provider=%s accessible_functions=%s",
            author.id,
            title,
            provider_name,
            accessible_functions,
        )

        if provider_name:
            provider_obj = Provider.objects.filter(name=provider_name).first()
            if provider_obj is None or not ProviderAccessPolicy.can_upload_function(
                user=author,
                provider=provider_obj,
                function_title=title,
                accessible_functions=accessible_functions,
            ):
                # For security we just return a 404 not a 401
                return Response(
                    {"message": f"Provider [{provider_name}] was not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            program = serializer.retrieve_provider_function(title=title, provider_name=provider_name)
        else:
            program = serializer.retrieve_private_function(title=title, author=author)

        if program is not None:
            serializer = self.get_serializer_upload_program(program, data=request.data)
            if not serializer.is_valid():
                logger.error(
                    "[programs-upload] user_id=%s validation failed on update: %s",
                    author.id,
                    serializer.errors,
                )
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(author=author, title=title, provider=provider_name)

        logger.info(
            "[programs-upload] user_id=%s program=%s provider=%s | Function uploaded ok",
            author.id,
            title,
            provider_name,
        )
        return Response(serializer.data)

    @_trace
    @action(methods=["POST"], detail=False)
    @endpoint_handle_exceptions
    def run(self, request):  # pylint: disable=too-many-locals,too-many-return-statements
        """Enqueues existing program."""
        serializer = self.get_serializer_run_program(data=request.data)
        if not serializer.is_valid():
            logger.error(
                "[programs-run] user_id=%s RunProgramSerializer validation failed: %s",
                request.user.id,
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        author = request.user
        # The sanitization should happen in the serializer
        # but it's here until we can refactor the /run end-point
        provider_name = sanitize_name(serializer.data.get("provider"))
        function_title = sanitize_name(serializer.data.get("title"))
        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-run] user_id=%s function=%s provider=%s accessible_functions=%s",
            author.id,
            function_title,
            provider_name,
            accessible_functions,
        )

        business_model = None
        if accessible_functions.use_legacy_authorization:
            function = Function.objects.get_function_by_permission(
                user=author,
                legacy_permission_name=RUN_PROGRAM_PERMISSION,
                function_title=function_title,
                provider_name=provider_name,
                filter_function_names=None,
            )
        else:
            if provider_name:
                function = Function.objects.get_function(function_title, provider_name)
                if function is None:
                    return Response(
                        {"message": f"Qiskit Pattern [{function_title}] was not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                if not accessible_functions.has_permission_for_function(
                    provider_name, function_title, PLATFORM_PERMISSION_RUN
                ):
                    return Response(
                        {"message": f"Qiskit Pattern [{function_title}] was not found."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                business_model = accessible_functions.get_function(provider_name, function_title).business_model
            else:
                function = Function.objects.get_user_function(author, function_title)

        if function is None:
            logger.error("[programs-run] user_id=%s function not found: %s", author.id, function_title)
            return Response(
                {"message": f"Qiskit Pattern [{function_title}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if function.disabled:
            error_message = (
                function.disabled_message if function.disabled_message else Function.DEFAULT_DISABLED_MESSAGE
            )
            return Response(
                {"message": error_message},
                status=status.HTTP_423_LOCKED,
            )

        jobconfig = None
        config_json = serializer.data.get("config")
        if config_json:
            job_config_serializer = self.get_serializer_job_config(data=config_json)
            if not job_config_serializer.is_valid():
                logger.error(
                    "[programs-run] user_id=%s JobConfigSerializer validation failed: %s",
                    author.id,
                    serializer.errors,
                )
                return Response(job_config_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            jobconfig = job_config_serializer.save()

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
                "[programs-run] user_id=%s RunJobSerializer validation failed: %s",
                author.id,
                serializer.errors,
            )
            return Response(job_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        if active_jobs_limit_reached(author):
            logger.error(
                "[programs-run] user_id=%s active jobs limit reached (%s)",
                author.id,
                settings.LIMITS_ACTIVE_JOBS_PER_USER,
            )
            raise ActiveJobLimitExceeded()
        # Extract and validate compute_profile from request if provided
        compute_profile = request.data.get("compute_profile")
        if compute_profile:
            # Validate compute_profile format (must be lowercase)
            if not re.match(r"^[a-z]+\d+[a-z]?-\d+x\d+(?:x\d+[a-z0-9]+)?$", compute_profile):
                error_msg = (
                    f"Invalid compute profile format: '{compute_profile}'. "
                    f"Expected format: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type] "
                    f"(lowercase only, e.g., 'cx3d-4x16' or 'gx3d-24x120x1a100p')"
                )
                return Response({"compute_profile": [error_msg]}, status=status.HTTP_400_BAD_REQUEST)

        save_kwargs = {
            "author": author,
            "carrier": carrier,
            "channel": channel,
            "token": token,
            "config": jobconfig,
            "instance": instance,
            "compute_profile": compute_profile,
            "business_model": business_model,
        }
        job = job_serializer.save(**save_kwargs)
        logger.info("[programs-run] user_id=%s job_id=%s program=%s | Job queued ok", author.id, job.id, function_title)
        return Response(job_serializer.data)

    @action(methods=["GET"], detail=False, url_path="get_by_title/(?P<title>[^/.]+)")
    def get_by_title(self, request, title):
        """Returns programs by title."""
        author = self.request.user
        function_title = sanitize_name(title)
        provider_name = sanitize_name(request.query_params.get("provider", None))

        serializer = self.get_serializer_upload_program(data=self.request.data)
        provider_name, function_title = serializer.get_provider_name_and_title(provider_name, function_title)

        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-get-by-title] user_id=%s program=%s provider=%s accessible_functions=%s",
            author.id,
            function_title,
            provider_name,
            accessible_functions,
        )

        if provider_name:
            # Only filter by function names from Runtime API /functions if use_legacy_authorization == False
            filter_fns = (
                accessible_functions.get_functions_by_provider(PLATFORM_PERMISSION_READ)
                if not accessible_functions.use_legacy_authorization
                else None
            )
            function = Function.objects.get_function_by_permission(
                user=author,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
                function_title=function_title,
                provider_name=provider_name,
                filter_function_names=filter_fns,
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
            function = Function.objects.get_user_function(author, function_title)
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

        logger.info(
            "[programs-get-by-title] user_id=%s program=%s provider=%s | Function retrieved ok",
            author.id,
            function_title,
            provider_name,
        )
        return Response(self.get_serializer(function).data)

    # This end-point is deprecated and we need to confirm if we can remove it
    @_trace
    @action(methods=["GET"], detail=True)
    def get_jobs(self, request, pk=None):  # pylint: disable=invalid-name,unused-argument
        """Returns jobs of the program."""
        program = Function.objects.filter(id=pk).first()
        if not program:
            return Response(
                {"message": f"program [{pk}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
        logger.info(
            "[programs-get-jobs] user_id=%s program_id=%s program=%s accessible_functions=%s",
            request.user.id,
            pk,
            program.title,
            accessible_functions,
        )

        user_is_provider = False
        if program.provider:
            user_is_provider = ProviderAccessPolicy.can_list_jobs(
                user=request.user,
                provider=program.provider,
                function_title=program.title,
                accessible_functions=accessible_functions,
            )

        if user_is_provider:
            jobs = Job.objects.filter(program=program)
        else:
            jobs = Job.objects.filter(program=program, author=request.user)
        serializer = self.get_serializer_job(jobs, many=True)
        logger.info(
            "[programs-get-jobs] user_id=%s program_id=%s program=%s | Jobs listed ok",
            request.user.id,
            pk,
            program.title,
        )
        return Response(serializer.data)
