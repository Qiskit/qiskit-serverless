# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
======================================================
Decorators (:mod:`quantum_serverless.core.decorators`)
======================================================

.. currentmodule:: quantum_serverless.core.decorators

Quantum serverless decorators
=============================

.. autosummary::
    :toctree: ../stubs/

    get
    put
    run_qiskit_remote
    get_refs_by_status
"""
import functools
import os
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, List, Callable

import ray
from opencensus.trace.span_context import generate_trace_id, generate_span_id
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import NonRecordingSpan, set_span_in_context, SpanContext
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from ray.runtime_env import RuntimeEnv
from rstr import rstr

from quantum_serverless.core.constrants import (
    META_TOPIC,
    QS_EXECUTION_WORKLOAD_ID,
    QS_EXECUTION_UID,
)
from quantum_serverless.core.events import (
    RedisEventHandler,
    ExecutionMessage,
    EventHandler,
)
from quantum_serverless.core.state import StateHandler
from quantum_serverless.utils import JsonSerializable

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

remote = ray.remote
get = ray.get
put = ray.put
get_refs_by_status = ray.wait


@dataclass
class Target(JsonSerializable):
    """Quantum serverless target.

    Example:
        >>> @run_qiskit_remote(target=Target(cpu=1))
        >>> def awesome_function():
        >>>     return 42
    """

    cpu: int = 1
    gpu: int = 0
    qpu: int = 0
    mem: int = 1
    resources: Optional[Dict[str, float]] = None
    env_vars: Optional[Dict[str, Any]] = None
    pip: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, dictionary: dict):
        return Target(**dictionary)


OT_PROGRAM_NAME = "OT_PROGRAM_NAME"
OT_JAEGER_HOST = "OT_JAEGER_HOST"
OT_JAEGER_HOST_KEY = "OT_JAEGER_HOST_KEY"
OT_JAEGER_PORT_KEY = "OT_JAEGER_PORT_KEY"
OT_TRACE_ID_KEY = "OT_TRACE_ID_KEY"


def traced(
        name: str,
        target: Target,
        trace_id: Optional[str] = None
) -> Callable:
    """Wrap a function in an OTel span.

    Args:
        name: name of function
        target: target for function
        trace_id: trace id

    Returns:
        traced function
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wraps(*args, **kwargs):
            traceparent = f"42-{trace_id or generate_trace_id()}-{generate_span_id()}-01"
            carrier = {"traceparent": traceparent}

            ctx = TraceContextTextMapPropagator().extract(carrier)

            resource = Resource(attributes={SERVICE_NAME: "quantum_serverless"})
            jaeger_exporter = JaegerExporter(
                agent_host_name=os.environ.get(OT_JAEGER_HOST_KEY, "localhost"),
                agent_port=int(os.environ.get(OT_JAEGER_PORT_KEY, 6831)),
            )
            provider = TracerProvider(resource=resource)
            processor = SimpleSpanProcessor(jaeger_exporter)
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
            tracer = trace.get_tracer(func.__module__)

            with tracer.start_as_current_span(name, context=ctx) as rollspan:
                rollspan.set_attribute("function_name", name)
                rollspan.set_attribute("stack_layer", "quantum_serverless")

                rollspan.set_attribute("cpu", target.cpu)
                rollspan.set_attribute("memory", target.mem)
                rollspan.set_attribute("gpu", target.gpu)

                resources = target.resources or {}
                for resource_name, resource_value in resources.items():
                    rollspan.set_attribute(resource_name, resource_value)

                if target.pip is not None:
                    rollspan.set_attribute("requirements", target.pip)

                return func(*args, **kwargs)

        return wraps

    return decorator


def run_qiskit_remote(
    target: Optional[Union[Dict[str, Any], Target]] = None,
    state: Optional[StateHandler] = None
):
    """Wraps local function as remote executable function.
    New function will return reference object when called.

    Example:
        >>> import quantum_serverless as qs
        >>>
        >>> @run_qiskit_remote()
        >>> def awesome_function(seed: int):
        >>>     return 42
        >>>
        >>> reference = awesome_function()
        >>> function_result = qs.get(reference)

    Args:
        target: target object or dictionary for requirements for node resources
        state: state handler
        events: events handler

    Returns:
        object reference
    """
    if target is None:
        target = Target(cpu=1)

    if isinstance(target, Target):
        remote_target = target
    else:
        remote_target = Target.from_dict(target)

    def decorator(function):
        def wrapper(*args, **kwargs):
            # inject state as an argument when passed in decorator
            if state is not None:
                args = tuple([state] + list(args))

            # runtime env
            # TODO: fix runtime_env warning
            env_vars = remote_target.env_vars or {}
            if env_vars.get(OT_TRACE_ID_KEY, None) is not None:
                env_vars[OT_TRACE_ID_KEY] = env_vars.get(OT_TRACE_ID_KEY)
            elif os.environ.get(OT_TRACE_ID_KEY) is not None:
                env_vars[OT_TRACE_ID_KEY] = os.environ.get(OT_TRACE_ID_KEY)
            else:
                env_vars[OT_TRACE_ID_KEY] = generate_trace_id()

            runtime_env = RuntimeEnv(env_vars=env_vars, pip=remote_target.pip)

            # tracing
            traced_function = traced(
                name=function.__name__,
                target=remote_target,
                trace_id=env_vars.get(OT_TRACE_ID_KEY)
            )(function)

            # remote function
            result = ray.remote(
                num_cpus=remote_target.cpu,
                num_gpus=remote_target.gpu,
                resources=remote_target.resources,
                memory=remote_target.mem,
                runtime_env=runtime_env,
            )(traced_function).remote(*args, **kwargs)

            return result

        return wrapper

    return decorator
