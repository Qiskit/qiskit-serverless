from unittest.mock import MagicMock, patch


def test_get_tracer_uses_http_exporter():
    """OTLPSpanExporter in client tracing is sourced from HTTP package."""
    from qiskit_serverless.core import tracing as tracing_module
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as HttpExporter,
    )
    assert tracing_module.OTLPSpanExporter is HttpExporter


def test_get_tracer_builds_http_endpoint():
    """get_tracer constructs a full http:// URL for the OTLP HTTP exporter."""
    with patch("qiskit_serverless.core.tracing.OTLPSpanExporter") as mock_exporter:
        mock_exporter.return_value = MagicMock()
        from qiskit_serverless.core.tracing import get_tracer
        get_tracer("test_module", agent_host="localhost", agent_port=4318)

        # Check that OTLPSpanExporter was called with the correct endpoint
        assert mock_exporter.called
        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs.get("endpoint") == "http://localhost:4318/v1/traces"


def test_get_tracer_no_insecure_param():
    """HTTP exporter does not accept insecure= — verify it is not passed."""
    with patch("qiskit_serverless.core.tracing.OTLPSpanExporter") as mock_exporter:
        mock_exporter.return_value = MagicMock()
        from qiskit_serverless.core.tracing import get_tracer
        get_tracer("test_module", agent_host="localhost", agent_port=4318)

        # Check that insecure parameter is not passed
        assert mock_exporter.called
        call_kwargs = mock_exporter.call_args[1]
        assert "insecure" not in call_kwargs


def test_setup_tracing_builds_http_endpoint(monkeypatch):
    """setup_tracing (Ray) constructs a full http:// URL."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HOST", "ray-collector")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PORT", "4318")
    monkeypatch.setenv("OTEL_ENABLED", "0")

    with patch("qiskit_serverless.core.tracing.OTLPSpanExporter") as mock_exporter:
        mock_exporter.return_value = MagicMock()
        from qiskit_serverless.core.tracing import setup_tracing
        setup_tracing()

        # Check that OTLPSpanExporter was called with the correct endpoint
        assert mock_exporter.called
        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs.get("endpoint") == "http://ray-collector:4318/v1/traces"
