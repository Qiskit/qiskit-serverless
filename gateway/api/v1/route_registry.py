"""
RouteRegistry Module
"""

from typing import Callable, List
from django.urls import path
from django.urls.resolvers import URLPattern


class RouteRegistry:
    """
    RouteRegistry class is used for register routes like views endpoints.
    """

    _routes: List[URLPattern] = []

    @classmethod
    def register(cls, url_path: str, view_func: Callable, name: str):
        """
        register a route to serve as endpoint.
        """
        if not url_path.endswith("/"):
            url_path += "/"

        route = path(url_path, view_func, name=name)
        cls._routes.append(route)

    @classmethod
    def get(cls) -> List[URLPattern]:
        """
        get all the routes
        """
        return cls._routes
