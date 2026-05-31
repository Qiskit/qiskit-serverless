from unittest.mock import MagicMock, patch


def test_setup_gateway_tracing_does_nothing_when_disabled(monkeypatch):
    """When OTEL_ENABLED=0, no provider is installed."""
    monkeypatch.setenv("OTEL_ENABLED", "0")

    from opentelemetry import trace as otel_trace

    original_provider = otel_trace.get_tracer_provider()

    from main.tracing import setup_gateway_tracing

    setup_gateway_tracing()

    assert otel_trace.get_tracer_provider() is original_provider


def test_setup_gateway_tracing_uses_http_exporter(monkeypatch):
    """OTLPSpanExporter is sourced from the HTTP package, not gRPC."""
    monkeypatch.setenv("OTEL_ENABLED", "0")

    from main import tracing as tracing_module
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as HttpExporter,
    )

    assert tracing_module.OTLPSpanExporter is HttpExporter


def test_setup_gateway_tracing_default_endpoint(monkeypatch):
    """Default endpoint is the OTLP/HTTP port 4318 with /v1/traces path."""
    monkeypatch.setenv("OTEL_ENABLED", "1")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)

    captured = {}

    with (
        patch("main.tracing.OTLPSpanExporter") as mock_exporter,
        patch("main.tracing.TracerProvider"),
        patch("main.tracing.BatchSpanProcessor"),
        patch("main.tracing.trace"),
        patch("main.tracing.DjangoInstrumentor"),
        patch("main.tracing.Psycopg2Instrumentor"),
    ):
        mock_exporter.return_value = MagicMock()
        import sys

        if "main.tracing" in sys.modules:
            del sys.modules["main.tracing"]
        from main import tracing

        tracing.setup_gateway_tracing()
        captured["endpoint"] = mock_exporter.call_args[1].get(
            "endpoint", mock_exporter.call_args[0][0] if mock_exporter.call_args[0] else None
        )

    assert captured["endpoint"] == "http://otel-collector:4318/v1/traces"


def test_setup_gateway_tracing_no_insecure_param(monkeypatch):
    """HTTP exporter does not accept insecure= — verify it is not passed."""
    monkeypatch.setenv("OTEL_ENABLED", "1")

    with (
        patch("main.tracing.OTLPSpanExporter") as mock_exporter,
        patch("main.tracing.TracerProvider"),
        patch("main.tracing.BatchSpanProcessor"),
        patch("main.tracing.trace"),
        patch("main.tracing.DjangoInstrumentor"),
        patch("main.tracing.Psycopg2Instrumentor"),
    ):
        mock_exporter.return_value = MagicMock()
        import sys

        if "main.tracing" in sys.modules:
            del sys.modules["main.tracing"]
        from main import tracing

        tracing.setup_gateway_tracing()
        kwargs = mock_exporter.call_args[1] if mock_exporter.call_args else {}

    assert "insecure" not in kwargs
