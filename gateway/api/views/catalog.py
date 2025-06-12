"""
Django Rest framework Catalog views for api application:

Version views inherit from the different views.
"""
import logging
import os

from django.conf import settings
from django.contrib.auth.models import Group

# pylint: disable=duplicate-code
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from rest_framework.decorators import action
from rest_framework import viewsets, status
from rest_framework.response import Response

from api.models import Program
from api.serializers import RetrieveCatalogSerializer
from api.decorators.trace_decorator import trace_decorator_factory

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

_trace = trace_decorator_factory("files")


class CatalogViewSet(viewsets.GenericViewSet):
    """ViewSet to handle requests from IQP for the catalog page.

    This ViewSet contains public end-points to retrieve information.
    """

    BASE_NAME = "catalog"
    PUBLIC_GROUP_NAME = settings.PUBLIC_GROUP_NAME

    @staticmethod
    def get_serializer_retrieve_catalog(*args, **kwargs):
        """
        This method returns Retrieve Catalog serializer to be used in Catalog ViewSet.
        """

        return RetrieveCatalogSerializer(*args, **kwargs)

    def get_queryset(self):
        """
        QuerySet to list public programs in the catalog
        """
        public_group = Group.objects.filter(name=self.PUBLIC_GROUP_NAME).first()

        if public_group is None:
            logger.error("Public group [%s] does not exist.", self.PUBLIC_GROUP_NAME)
            return []

        return Program.objects.filter(instances=public_group).distinct()

    def get_retrieve_queryset(self, pk):
        """
        QuerySet to retrieve a specifc public programs in the catalog
        """
        public_group = Group.objects.filter(name=self.PUBLIC_GROUP_NAME).first()

        if public_group is None:
            logger.error("Public group [%s] does not exist.", self.PUBLIC_GROUP_NAME)
            return None

        return Program.objects.filter(id=pk, instances=public_group).first()

    def get_by_title_queryset(self, title, provider_name):
        """
        QuerySet to retrieve a specifc public programs in the catalog
        """
        public_group = Group.objects.filter(name=self.PUBLIC_GROUP_NAME).first()

        if public_group is None:
            logger.error("Public group [%s] does not exist.", self.PUBLIC_GROUP_NAME)
            return None

        return Program.objects.filter(
            title=title, provider__name=provider_name, instances=public_group
        ).first()

    @_trace
    def list(self, request):
        """List public programs in the catalog:"""
        user = None
        if request.user and request.user.is_authenticated:
            user = request.user
        serializer = self.get_serializer(
            self.get_queryset(), context={"user": user}, many=True
        )
        return Response(serializer.data)

    @_trace
    def retrieve(self, request, pk=None):
        """Get a specific program in the catalog:"""
        instance = self.get_retrieve_queryset(pk)
        if instance is None:
            return Response(
                {"message": "Qiskit Function not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = None
        if request.user and request.user.is_authenticated:
            user = request.user
        serializer = self.get_serializer_retrieve_catalog(
            instance, context={"user": user}
        )
        return Response(serializer.data)

    @_trace
    @action(methods=["GET"], detail=False)
    def get_by_title(self, request):
        """Get a specific program in the catalog:"""
        title = self.request.query_params.get("title")
        provider_name = self.request.query_params.get("provider")
        if not title or not provider:
            return Response(
                {"message": "Missing title or provider name."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance = self.get_by_title_queryset(title, provider_name)
        if instance is None:
            return Response(
                {"message": "Qiskit Function not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = None
        if request.user and request.user.is_authenticated:
            user = request.user
        serializer = self.get_serializer_retrieve_catalog(
            instance, context={"user": user}
        )
        return Response(serializer.data)
