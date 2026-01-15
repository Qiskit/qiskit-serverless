# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
=================================================
Provider (:mod:`qiskit_serverless.core.tracing`)
=================================================

.. currentmodule:: qiskit_serverless.core.tracing

Qiskit Serverless tracing
==========================

.. autosummary::
    :toctree: ../stubs/

    get_tracer
"""

import os
from typing import Dict, Optional

from opentelemetry import trace  # pylint: disable=duplicate-code
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from qiskit_serverless.core.config import Config
from qiskit_serverless.core.constants import (
    OT_TRACEPARENT_ID_KEY,
    OT_SPAN_DEFAULT_NAME,
    OT_LABEL_CALL_LOCATION,
)


def get_tracer(
    instrumenting_module_name: str,
    agent_host: Optional[str] = None,
    agent_port: Optional[int] = None,
) -> Tracer:
    """Returns tracer for context.

    If agent host and ports are not provided default tracer will be returned.
    If agent host and ports are provided then will include Jaeger as provider.

    Args:
        instrumenting_module_name: module name for tracing
        agent_host: jaeger agent host
        agent_port: jaeger agent port

    Returns:
        tracer
    """
    resource = Resource(attributes={SERVICE_NAME: f"qs.{Config.ot_program_name()}"})
    provider = TracerProvider(resource=resource)
    if agent_host is not None and agent_port is not None:
        otel_exporter = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{agent_host}:{agent_port}",
                insecure=Config.ot_insecure(),
            )
        )
        provider.add_span_processor(otel_exporter)
    if Config.ot_enabled():
        trace._set_tracer_provider(  # pylint: disable=protected-access
            provider, log=False
        )
    return trace.get_tracer(instrumenting_module_name)


def _trace_env_vars(env_vars: dict, location: Optional[str] = None):
    """Sets env variables for tracing across executable function.

    Args:
        env_vars: original env variables dict to inject traceparent
        location: where trace was called

    Returns:
        dict of env variables
    """
    if Config.ot_ray_tracer():
        tracer = trace.get_tracer("Qiskit-Serverless")
    else:
        tracer = get_tracer(
            __name__,
            agent_host=Config.ot_jaeger_host(),
            agent_port=Config.ot_jaeger_port(),
        )
    if env_vars.get(OT_TRACEPARENT_ID_KEY, None) is not None:
        env_vars[OT_TRACEPARENT_ID_KEY] = env_vars.get(OT_TRACEPARENT_ID_KEY)
    elif Config.ot_traceparent_id() is not None:
        env_vars[OT_TRACEPARENT_ID_KEY] = Config.ot_traceparent_id()
    else:
        carrier: Dict[str, str] = {}
        with tracer.start_as_current_span(
            Config.ot_program_name()
            if Config.ot_program_name() != "unnamed_execution"
            else OT_SPAN_DEFAULT_NAME
        ) as span:
            if location is not None:
                span.set_attribute(OT_LABEL_CALL_LOCATION, location)
            TraceContextTextMapPropagator().inject(carrier)
        traceparent = carrier.get(
            TraceContextTextMapPropagator._TRACEPARENT_HEADER_NAME  # pylint:disable=protected-access
        )
        if traceparent:
            env_vars[OT_TRACEPARENT_ID_KEY] = traceparent
            os.environ[OT_TRACEPARENT_ID_KEY] = traceparent
    return env_vars


def setup_tracing() -> None:
    """Setup Tracing for Ray cluster

    Passed as an argument at Ray start
    """
    agent_host = Config.ot_jaeger_host()
    agent_port = Config.ot_jaeger_port()
    resource = Resource(attributes={SERVICE_NAME: "Qiskit-Serverless: Ray"})
    provider = TracerProvider(resource=resource)
    otel_exporter = BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=f"{agent_host}:{agent_port}",
            insecure=Config.ot_insecure(),
        )
    )
    provider.add_span_processor(otel_exporter)
    if Config.ot_enabled():
        trace._set_tracer_provider(  # pylint: disable=protected-access
            provider, log=False
        )
