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

    remote
"""

import functools
from types import FunctionType
from typing import Union

from opentelemetry import trace


def _require_ray():
    """Import Ray lazily, with a clear error if the optional extra is missing.

    Ray is an optional dependency (``pip install qiskit-serverless[ray]``); it is
    only needed for the Ray runner. Importing the package must not require it, so
    the Ray-only helpers below import it on demand.
    """
    # pylint: disable=import-outside-toplevel,import-error
    try:
        import ray

        return ray
    except ModuleNotFoundError as err:
        raise ModuleNotFoundError(
            "Ray is required for this feature but is not installed. "
            "Install it with `pip install qiskit-serverless[ray]`."
        ) from err


def remote(*args, **kwargs):
    """Proxy for ``ray.remote`` that defers importing Ray until use.

    Forwards to ``ray.remote`` and therefore supports both ``@remote`` and
    ``remote(num_cpus=...)(fn)`` usages, while keeping ``import qiskit_serverless``
    Ray-free (Ray is the optional ``qiskit-serverless[ray]`` extra).
    """
    return _require_ray().remote(*args, **kwargs)


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
                function_name = traced_function if isinstance(traced_function, str) else func.__name__
                with tracer.start_as_current_span(f"{traced_feature}.{function_name}"):
                    result = func(*args, **kwargs)
                return result

            return wrapper

        if callable(traced_function):
            return decorator_trace(traced_function)
        return decorator_trace

    return generated_decorator
