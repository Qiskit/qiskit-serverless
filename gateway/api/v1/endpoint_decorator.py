"""
Endpoint decorator Module
"""

from functools import wraps
from typing import Callable

from rest_framework.decorators import api_view

from api.v1.route_registry import RouteRegistry


def endpoint(url_path: str, method: str, name: str = None):
    """
    endpoint decorator for views
    """

    def decorator(view_func: Callable):
        if name is None:
            module_path = view_func.__module__
            parts = module_path.split(".views.", 2)

            if len(parts) == 2:
                relative_path = parts[1]
            else:
                relative_path = module_path  # fallback

            generated_name = relative_path.replace(".", "-").replace("_", "-")
        else:
            generated_name = name.replace("_", "-")

        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            return view_func(*args, **kwargs)

        # Auto-wrap with api_view for DRF request handling (auth, parsing, etc.).
        # The method restriction is also enforced by the combined dispatcher in RouteRegistry,
        # but having it here keeps each handler self-consistent.
        drf_view = api_view([method])(wrapped_view)
        # Copy .cls/.initkwargs so @swagger_auto_schema(method=...) applied to wrapped_view
        # (which we return) recognises it as an api_view function.
        wrapped_view.cls = drf_view.cls
        wrapped_view.initkwargs = drf_view.initkwargs
        # Store back-ref so _build_combined_view can find _swagger_auto_schema,
        # which is set on wrapped_view (returned to callers) after this decorator runs.
        drf_view.__endpoint_wrapped__ = wrapped_view
        RouteRegistry.register(url_path, drf_view, generated_name, method=method)

        return wrapped_view

    return decorator
