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
Decorators (:mod:`qiskit_serverless.core.decorators`)
======================================================

.. currentmodule:: qiskit_serverless.core.decorators

Qiskit Serverless decorators
=============================

.. autosummary::
    :toctree: ../stubs/

    get
    put
    run_qiskit_remote
    get_refs_by_status
    distribute_task
    distribute_program
"""
import functools
import inspect
import os
import shutil
from types import FunctionType
import warnings
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union, List, Callable, Sequence
from uuid import uuid4

import cloudpickle
import ray
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from qiskit import QuantumCircuit
from ray.runtime_env import RuntimeEnv

from qiskit_serverless.core.constants import (
    OT_ATTRIBUTE_PREFIX,
    OT_JAEGER_HOST_KEY,
    OT_JAEGER_PORT_KEY,
    OT_TRACEPARENT_ID_KEY,
    OT_RAY_TRACER,
)
from qiskit_serverless.core.tracing import get_tracer, _trace_env_vars
from qiskit_serverless.utils import JsonSerializable

remote = ray.remote


def put(value: Any, **kwargs):
    """Puts object into shared distributed storage

    Args:
        value: object to put to object store
        **kwargs: other arguments

    Returns:

    """
    return ray.put(value=value, **kwargs)


def get_refs_by_status(object_refs: List["ray.ObjectRef"], **kwargs):
    """Get references by status.

    Args:
        object_refs: object references
        **kwargs: other arguments

    Returns:
        A list of refs that are ready and a list of the remaining references.
    """
    return ray.wait(ray_waitables=object_refs, **kwargs)


def get(
    object_refs: Union[ray.ObjectRef, Sequence[ray.ObjectRef]],
    *,
    timeout: Optional[float] = None,
) -> Any:
    """Get results from distributed tasks.

    Args:
        object_refs: Object ref of the object to get or a list of object refs
            to get.
        timeout (Optional[float]): The maximum amount of time in seconds to
            wait before returning.

    Returns:
        A object or a list of objects.
    """
    return ray.get(object_refs=object_refs, timeout=timeout)


@dataclass
class Target(JsonSerializable):
    """Qiskit Serverless target.

    Example:
        >>> @distribute_task(target=Target(cpu=1))
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


@dataclass
class CircuitMeta:
    """Circuit metainformation."""

    num_qubits: int
    depth: int

    def to_seq(self) -> Sequence[int]:
        """Converts meta to seq."""
        return [self.num_qubits, self.depth]


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
        return CircuitMeta(num_qubits=circuit.num_qubits, depth=circuit.depth())

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
            if bool(int(os.environ.get(OT_RAY_TRACER, "0"))):
                tracer = trace.get_tracer(func.__module__)
            else:
                tracer = get_tracer(
                    func.__module__,
                    agent_host=os.environ.get(OT_JAEGER_HOST_KEY, None),
                    agent_port=int(os.environ.get(OT_JAEGER_PORT_KEY, 6831)),
                )
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
                    f"{OT_ATTRIBUTE_PREFIX}.meta.stack_layer", "qiskit_serverless"
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


def distribute_task(
    target: Optional[Union[Dict[str, Any], Target]] = None,
):
    """Wraps local function as remote executable function.
    New function will return reference object when called.

    Example:
        >>> import qiskit_serverless as qs
        >>>
        >>> @distribute_task()
        >>> def awesome_function(seed: int):
        >>>     return 42
        >>>
        >>> reference = awesome_function()
        >>> function_result = qs.get(reference)

    Args:
        target: target object or dictionary for requirements for node resources

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
            # tracing
            traced_env_vars = _trace_env_vars(
                remote_target.env_vars or {}, location="on decoration"
            )
            traced_function = _tracible_function(
                name=function.__name__,
                target=remote_target,
                trace_id=traced_env_vars.get(OT_TRACEPARENT_ID_KEY),
            )(function)

            # runtime env
            runtime_env = RuntimeEnv(pip=remote_target.pip, env_vars=traced_env_vars)

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


ENTRYPOINT_CONTENT = """
import cloudpickle
from qiskit_serverless import get_arguments, save_result

arguments = get_arguments()

with open("./{file_name}", "rb") as file:
    function = cloudpickle.load(file)

    result = function(**arguments)
    if result is not None:
        save_result(result)
"""


def distribute_qiskit_function(
    provider: Optional[Any] = None,
    dependencies: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
):
    """[Experimental] QiskitFunction decorator to turn function into remotely executable program.

    Example:
        >>> @distribute_qiskit_function(provider=ServerlessProvider(...), dependencies=[...])
        >>> def my_program():
        >>>     print("Hola!")
        >>>
        >>> job = my_program()

    Args:
        provider: provider to use for program execution
        dependencies: dependencies for program
        working_dir: working directory, which will be shipped for remote execution

    Returns:
        remotely executable program
    """
    # pylint: disable=import-outside-toplevel,cyclic-import
    from qiskit_serverless import QiskitServerlessException
    from qiskit_serverless.core.function import QiskitFunction
    from qiskit_serverless import ServerlessClient

    # create provider
    if provider is None:
        # try to create from env vars
        try:
            provider = ServerlessClient()
        except QiskitServerlessException as qs_error:
            raise QiskitServerlessException(
                "Set provider in arguments for `distribute_program` "
                "decorator or define env variables."
            ) from qs_error
    if provider is None:
        raise QiskitServerlessException(
            "Provider was not defined. "
            "Please, pass provider to @distribute_program decorator or setup env variables."
        )

    def decorator(function):
        """Decorator."""
        if not inspect.isfunction(function):
            raise QiskitServerlessException(
                "Only functions are supported by this decorator."
            )

        def wrapper(*args, **kwargs):
            """Function wrapper."""
            suffix = str(uuid4())[:8]

            if len(args) > 0:
                raise QiskitServerlessException(
                    f"Only named arguments supported at this moment. "
                    f"Please specify name of argument of function {function.__name__}"
                )

            # create folder
            working_directory = (
                working_dir or f"./qs_artifacts/{function.__name__}_{suffix}"
            )
            os.makedirs(working_directory, exist_ok=True)

            # dump pickle
            pickle_file_name = f"pickle_{suffix}.pkl"
            pickle_file_path = f"{working_directory}/{pickle_file_name}"
            with open(pickle_file_path, "wb") as file:
                cloudpickle.dump(function, file)

            # create entrypoint
            entrypoint_file_name = f"entrypoint_{suffix}.py"
            entrypoint_file_path = f"{working_directory}/{entrypoint_file_name}"
            with open(entrypoint_file_path, "w", encoding="utf-8") as file:
                file.write(ENTRYPOINT_CONTENT.format(file_name=pickle_file_name))

            # create program
            wrapped_program = QiskitFunction(
                title=function.__name__,
                entrypoint=entrypoint_file_name,
                working_dir=working_directory,
                dependencies=dependencies,
                description="QiskitFunction execution using @distribute_program decorator.",
            )

            provider.upload(wrapped_program)

            # run program
            job = provider.run(wrapped_program, arguments=kwargs)

            # remove artifact files
            if os.path.exists(pickle_file_path):
                os.remove(pickle_file_path)
            if os.path.exists(entrypoint_file_path):
                os.remove(entrypoint_file_path)
            if working_dir is None and os.path.exists(working_directory):
                shutil.rmtree(working_directory)
            return job

        return wrapper

    return decorator


def distribute_program(
    provider: Optional[Any] = None,
    dependencies: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
):
    """Decorator for distributed program."""
    warnings.warn(
        "`distribute_program` has been deprecated "
        "and will be removed in future releases. "
        "Please, use `distribute_qiskit_function` instead."
    )
    return distribute_qiskit_function(provider, dependencies, working_dir)


def trace_decorator_factory(traced_feature: str):
    """Factory for generate decorators for classes or features."""

    def generated_decorator(traced_function: Union[FunctionType, str]):
        """
        The decorator wrapper to generate optional arguments
        if traced_function is string it will be used in the span,
        the function.__name__ attribute will be used otherwise
        """

        def decorator_trace(func: FunctionType):
            """The decorator that python call"""

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                """The wrapper"""
                tracer = trace.get_tracer("client.tracer")
                function_name = (
                    traced_function
                    if isinstance(traced_function, str)
                    else func.__name__
                )
                with tracer.start_as_current_span(f"{traced_feature}.{function_name}"):
                    result = func(*args, **kwargs)
                return result

            return wrapper

        if callable(traced_function):
            return decorator_trace(traced_function)
        return decorator_trace

    return generated_decorator
