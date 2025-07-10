from django.urls import path
from typing import Callable, List, Optional
from django.urls.resolvers import URLPattern

class RouteRegistry:
    _routes: List[URLPattern] = []

    @classmethod
    def register(cls, url_path: str, view_func: Callable, name: Optional[str] = None):
        route_name = name or view_func.__name__.replace('_', '-')
        if not url_path.endswith('/'):
            url_path += '/'
            
        route = path(url_path, view_func, name=route_name)
        cls._routes.append(route)
        print(f"[REGISTER] {url_path} → {route_name}")

    @classmethod
    def get(cls) -> List[URLPattern]:
        print(f"[ROUTES READY] {cls._routes}")
        return cls._routes
