"""
RouteRegistry Module
"""

from typing import Callable, Dict, List, Tuple
from django.urls import path
from django.urls.resolvers import URLPattern
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.views import APIView


class RouteRegistry:
    """
    RouteRegistry class is used for register routes like views endpoints.
    """

    _method_handlers: Dict[str, Dict[str, Tuple[Callable, str]]] = {}

    @classmethod
    def register(cls, url_path: str, view_func: Callable, name: str, method: str):
        """
        register a route to serve as endpoint.
        """
        if not url_path.endswith("/"):
            url_path += "/"

        clean_path = url_path.lstrip("/")

        if clean_path not in cls._method_handlers:
            cls._method_handlers[clean_path] = {}

        if method.upper() in cls._method_handlers[clean_path]:
            raise ValueError(f"Method {method.upper()} is already registered for path '{clean_path}'")

        cls._method_handlers[clean_path][method.upper()] = (view_func, name)

    @classmethod
    def _build_combined_view(cls, url_path: str, method_map: Dict[str, Tuple[Callable, str]]) -> URLPattern:
        """Build a single URL pattern that dispatches to per-method handlers.

        Django only allows one view per URL, so when multiple HTTP methods are registered
        to the same path (e.g. GET and POST on 'jobs/<id>/runtime_jobs/'), this creates
        a single callable that routes each request to the right handler.
        """
        name = next(iter(method_map.values()))[1]

        # method -> handler function, e.g. {"GET": get_func, "POST": post_func}
        handlers = {m: func for m, (func, _) in method_map.items()}

        # Merge swagger schemas from all handlers so the combined URL exposes all of them
        merged_swagger: dict = {}
        for func, _ in method_map.values():
            # When endpoint() auto-wraps with api_view, swagger is on __endpoint_wrapped__
            source = getattr(func, "__endpoint_wrapped__", func)
            merged_swagger.update(getattr(source, "_swagger_auto_schema", {}))

        # DRF middleware reads .cls on any callable it handles. We create a CombinedView
        # class solely for that introspection (it declares the allowed methods so that
        # swagger and OPTIONS responses are correct). It is never invoked directly.
        allowed_http_names = [m.lower() for m in method_map.keys()] + ["options"]

        def _stub(self, request, *args, **kwargs):  # pylint: disable=unused-argument
            pass

        combined_view_attrs = {"http_method_names": allowed_http_names}
        for m in method_map.keys():
            combined_view_attrs[m.lower()] = _stub
        CombinedView = type("CombinedView", (APIView,), combined_view_attrs)

        # The actual dispatcher: route to the right handler, 405 for unknown methods
        def dispatch(request, *args, **kwargs):
            handler = handlers.get(request.method.upper())
            if handler:
                return handler(request, *args, **kwargs)
            raise MethodNotAllowed(request.method)

        dispatch.cls = CombinedView  # required by DRF middleware for auth/permissions
        dispatch.initkwargs = {}
        dispatch.__name__ = name
        if merged_swagger:
            dispatch._swagger_auto_schema = merged_swagger  # pylint: disable=protected-access

        return path(url_path, dispatch, name=name)

    @classmethod
    def get(cls) -> List[URLPattern]:
        """
        get all the routes
        """
        return [cls._build_combined_view(url_path, method_map) for url_path, method_map in cls._method_handlers.items()]
