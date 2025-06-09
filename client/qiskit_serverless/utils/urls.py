def url_path_join(base, *parts):
    """
    Join URL parts with single slashes.
    """
    return "/".join([base.rstrip("/")] + [p.strip("/") for p in parts])