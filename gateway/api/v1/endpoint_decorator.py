from functools import wraps
from typing import Callable
from api.v1.route_registry import RouteRegistry

def endpoint(url_path: str, name: str = None):
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

        RouteRegistry.register(url_path, wrapped_view, generated_name)
        return wrapped_view
    return decorator

