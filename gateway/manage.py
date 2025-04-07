#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    resource = Resource(attributes={SERVICE_NAME: f"QiskitServerless-Gateway"})
    provider = TracerProvider(resource=resource)
    otel_exporter = BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=os.environ.get(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://otel-collector:4317"
            ),
            insecure=bool(
                int(os.environ.get("OTEL_EXPORTER_OTLP_TRACES_INSECURE", "0"))
            ),
        )
    )
    provider.add_span_processor(otel_exporter)
    if bool(int(os.environ.get("OTEL_ENABLED", "0"))):
        trace._set_tracer_provider(
            provider, log=False
        )  # pylint: disable=protected-access
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    API_KEY="admin123"
    main()

