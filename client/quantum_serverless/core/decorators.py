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
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, List, Callable, Sequence

import ray
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
)
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from qiskit import QuantumCircuit
from ray.runtime_env import RuntimeEnv

from quantum_serverless.core.state import StateHandler
from quantum_serverless.utils import JsonSerializable

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
OT_TRACEPARENT_ID_KEY = "OT_TRACEPARENT_ID_KEY"
OT_SPAN_DEFAULT_NAME = "entrypoint"
OT_ATTRIBUTE_PREFIX = "qs"


@dataclass
class CircuitMeta:
    """Circuit metainformation."""

    n_qubits: int
    depth: int

    def to_seq(self) -> Sequence[int]:
        """Converts meta to seq."""
        return [self.n_qubits, self.depth]


Numeric = Union[float, int]


def fetch_execution_meta(*args, **kwargs) -> Dict[str, Sequence[Numeric]]:
    """Extracts meta information from function arguments.

    Meta information consist of metrics that describe circuits.
    Metrics described in `CircuitMeta` class.

    Args:
        *args: arguments
        **kwargs: named arguments

    Returns:
        return meta information dictionary
    """

    def fetch_meta(circuit: QuantumCircuit) -> CircuitMeta:
        """Returns meta information from circuit."""
        return CircuitMeta(n_qubits=circuit.num_qubits, depth=circuit.depth())

    meta: Dict[str, Sequence[Numeric]] = {}

    for idx, argument in enumerate(args):
        if isinstance(argument, QuantumCircuit):
            meta[f"{OT_ATTRIBUTE_PREFIX}.args.arg_{idx}"] = fetch_meta(
                argument
            ).to_seq()
        elif isinstance(argument, list):
            for sub_idx, sub_argument in enumerate(argument):
                if isinstance(sub_argument, QuantumCircuit):
                    meta[
                        f"{OT_ATTRIBUTE_PREFIX}.args.arg_{idx}.{sub_idx}"
                    ] = fetch_meta(sub_argument).to_seq()
    for key, value in kwargs.items():
        if isinstance(value, QuantumCircuit):
            meta[f"{OT_ATTRIBUTE_PREFIX}.kwargs.{key}"] = fetch_meta(value).to_seq()
        elif isinstance(value, list):
            for sub_idx, sub_argument in enumerate(value):
                if isinstance(sub_argument, QuantumCircuit):
                    meta[f"{OT_ATTRIBUTE_PREFIX}.kwargs.{key}.{sub_idx}"] = fetch_meta(
                        sub_argument
                    ).to_seq()
    return meta


def get_tracer(instrumenting_module_name) -> Tracer:
    """Returns tracer for funciton."""
    resource = Resource(
        attributes={
            SERVICE_NAME: f"qs.{os.environ.get(OT_PROGRAM_NAME, 'unnamed_execution')}"
        }
    )
    jaeger_exporter = JaegerExporter(
        agent_host_name=os.environ.get(OT_JAEGER_HOST_KEY, "localhost"),
        agent_port=int(os.environ.get(OT_JAEGER_PORT_KEY, 6831)),
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(jaeger_exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(instrumenting_module_name)


def _trace_env_vars(env_vars: dict):
    tracer = get_tracer(__name__)
    if env_vars.get(OT_TRACEPARENT_ID_KEY, None) is not None:
        env_vars[OT_TRACEPARENT_ID_KEY] = env_vars.get(OT_TRACEPARENT_ID_KEY)
    elif os.environ.get(OT_TRACEPARENT_ID_KEY) is not None:
        env_vars[OT_TRACEPARENT_ID_KEY] = os.environ.get(OT_TRACEPARENT_ID_KEY)
    else:
        carrier: Dict[str, str] = {}
        with tracer.start_as_current_span(OT_SPAN_DEFAULT_NAME):
            TraceContextTextMapPropagator().inject(carrier)
        env_vars[OT_TRACEPARENT_ID_KEY] = carrier.get(
            TraceContextTextMapPropagator._TRACEPARENT_HEADER_NAME  # pylint:disable=protected-access
        )
    return env_vars


def _tracible_function(
    name: str, target: Target, trace_id: Optional[str] = None
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
            tracer = get_tracer(func.__module__)
            ctx = TraceContextTextMapPropagator().extract(
                {
                    TraceContextTextMapPropagator._TRACEPARENT_HEADER_NAME: trace_id  # pylint:disable=protected-access
                }
            )

            circuits_meta = fetch_execution_meta(*args, **kwargs)

            with tracer.start_as_current_span(name, context=ctx) as rollspan:
                # TODO: add serverless package version # pylint: disable=fixme
                rollspan.set_attribute(
                    f"{OT_ATTRIBUTE_PREFIX}.meta.function_name", name
                )
                rollspan.set_attribute(
                    f"{OT_ATTRIBUTE_PREFIX}.meta.stack_layer", "quantum_serverless"
                )

                rollspan.set_attribute(
                    f"{OT_ATTRIBUTE_PREFIX}.resources.cpu", target.cpu
                )
                rollspan.set_attribute(
                    f"{OT_ATTRIBUTE_PREFIX}.resources.memory", target.mem
                )
                rollspan.set_attribute(
                    f"{OT_ATTRIBUTE_PREFIX}.resources.gpu", target.gpu
                )

                resources = target.resources or {}
                for resource_name, resource_value in resources.items():
                    rollspan.set_attribute(
                        f"{OT_ATTRIBUTE_PREFIX}.resources.{resource_name}",
                        resource_value,
                    )

                if target.pip is not None:
                    rollspan.set_attribute("requirements", target.pip)

                for meta_key, meta_value in circuits_meta.items():
                    rollspan.set_attribute(meta_key, meta_value)

                return func(*args, **kwargs)

        return wraps

    return decorator


def run_qiskit_remote(
    target: Optional[Union[Dict[str, Any], Target]] = None,
    state: Optional[StateHandler] = None,
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

            # tracing
            traced_env_vars = _trace_env_vars(remote_target.env_vars or {})
            traced_function = _tracible_function(
                name=function.__name__,
                target=remote_target,
                trace_id=traced_env_vars.get(OT_TRACEPARENT_ID_KEY),
            )(function)

            # runtime env
            # TODO: fix runtime_env warning  # pylint: disable=fixme
            runtime_env = RuntimeEnv(env_vars=traced_env_vars, pip=remote_target.pip)

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
