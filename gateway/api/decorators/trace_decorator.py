"""
======================================================
Decorators (:mod:`gateway.api.decorators.trace_decorator`)
======================================================

.. currentmodule:: gateway.api.decorators.trace_decorator

Gateway API decorators
=============================

.. autosummary::
    :toctree: ../stubs/

    trace_decorator_factory
"""

from functools import wraps
from types import FunctionType
from typing import Union
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


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

            @wraps(func)
            def wrapper(*args, **kwargs):
                """The wrapper"""
                tracer = trace.get_tracer("gateway.tracer")
                function_name = traced_function if isinstance(traced_function, str) else func.__name__
                request = args[0]
                ctx = TraceContextTextMapPropagator().extract(carrier=request.headers)
                with tracer.start_as_current_span(f"gateway.{traced_feature}.{function_name}", context=ctx):
                    result = func(*args, **kwargs)
                return result

            return wrapper

        if callable(traced_function):
            return decorator_trace(traced_function)
        return decorator_trace

    return generated_decorator
