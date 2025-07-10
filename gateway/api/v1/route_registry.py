"""
RouteRegistry Module
"""

from typing import Callable, List, Optional
from django.urls import path
from django.urls.resolvers import URLPattern


class RouteRegistry:
    """
    RouteRegistry class is used for register routes like views endpoints.
    """

    _routes: List[URLPattern] = []

    @classmethod
    def register(cls, url_path: str, view_func: Callable, name: Optional[str] = None):
        """
        register a route to serve as endpoint.
        """
        route_name = name or view_func.__name__.replace("_", "-")
        if not url_path.endswith("/"):
            url_path += "/"

        route = path(url_path, view_func, name=route_name)
        cls._routes.append(route)

    @classmethod
    def get(cls) -> List[URLPattern]:
        """
        get all the routes
        """
        return cls._routes
