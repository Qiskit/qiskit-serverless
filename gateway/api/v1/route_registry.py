"""
RouteRegistry Module
"""

from typing import Callable, Dict, List, Optional, Tuple
from django.urls import path
from django.urls.resolvers import URLPattern
from rest_framework.views import APIView


class RouteRegistry:
    """
    RouteRegistry class is used for register routes like views endpoints.
    """

    _routes: List[URLPattern] = []
    _method_handlers: Dict[str, Dict[str, Tuple[Callable, str]]] = {}

    @classmethod
    def register(cls, url_path: str, view_func: Callable, name: str, method: Optional[str] = None):
        """
        register a route to serve as endpoint.
        """
        if not url_path.endswith("/"):
            url_path += "/"

        clean_path = url_path.lstrip("/")

        if method is None:
            cls._routes.append(path(clean_path, view_func, name=name))
            return

        if clean_path not in cls._method_handlers:
            cls._method_handlers[clean_path] = {}
        cls._method_handlers[clean_path][method.upper()] = (view_func, name)

    @classmethod
    def _build_combined_view(cls, url_path: str, method_map: Dict[str, Tuple[Callable, str]]) -> URLPattern:
        """Build a single URL pattern that dispatches to per-method handlers."""
        name = next(iter(method_map.values()))[1]
        all_methods = list(method_map.keys())
        handlers = {m: func for m, (func, _) in method_map.items()}

        merged_swagger: dict = {}
        for _, (func, _) in method_map.items():
            merged_swagger.update(getattr(func, "_swagger_auto_schema", {}))

        http_names = [m.lower() for m in all_methods] + ["options"]

        def _stub_handler(self, request, *args, **kwargs):
            pass

        combined_attrs = {"http_method_names": http_names}
        for m in all_methods:
            combined_attrs[m.lower()] = _stub_handler
        CombinedView = type("CombinedView", (APIView,), combined_attrs)

        def combined(request, *args, **kwargs):
            handler = handlers.get(request.method.upper())
            if handler:
                return handler(request, *args, **kwargs)
            from rest_framework.exceptions import MethodNotAllowed

            raise MethodNotAllowed(request.method)

        combined.cls = CombinedView
        combined.initkwargs = {}
        combined.__name__ = name
        if merged_swagger:
            combined._swagger_auto_schema = merged_swagger

        return path(url_path, combined, name=name)

    @classmethod
    def get(cls) -> List[URLPattern]:
        """
        get all the routes
        """
        routes = list(cls._routes)
        for url_path, method_map in cls._method_handlers.items():
            routes.append(cls._build_combined_view(url_path, method_map))
        return routes
