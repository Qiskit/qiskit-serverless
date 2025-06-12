"""
Utility functions for URL path manipulation.
"""


def url_path_join(base: str, *parts: str):
    """
    Join URL parts with single slashes.
    """
    return "/".join([base.rstrip("/")] + list(parts))
