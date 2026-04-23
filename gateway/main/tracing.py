"""Gateway OpenTelemetry tracing configuration."""

import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_gateway_tracing(service_name: str = "QiskitServerless-Gateway") -> None:
    """Configure OTLP tracing for the gateway process.

    Sets up a global TracerProvider with an OTLP gRPC exporter and
    enables Django auto-instrumentation for automatic HTTP request spans.
    This is a process-level singleton — call once at startup (e.g. in manage.py).

    Reads from environment:
        OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: collector endpoint (default: http://otel-collector:4317)
        OTEL_EXPORTER_OTLP_TRACES_INSECURE: use insecure gRPC (default: 0)
        OTEL_ENABLED: master on/off flag (default: 0)
    """
    resource = Resource(attributes={SERVICE_NAME: service_name})
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
    DjangoInstrumentor().instrument()
    Psycopg2Instrumentor().instrument()
