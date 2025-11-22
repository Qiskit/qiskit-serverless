"""
Custom middleware used by Qiskit Serverless API
"""

from api.context import set_current_user


def add_slash(get_response):
    """
    This middleware allows to do calls with and without slashes:
    - /api/v1/programs
    - /api/v1/programs/
    """

    def middleware(request):
        if request.path.startswith("/api") and not request.path.endswith("/"):
            request.path_info = request.path = f"{request.path}/"
        return get_response(request)

    return middleware


def current_user_context(get_response):
    """
    Middleware that sets the current user in the ContextVar, so it can be accessed later
    in other parts of the code where there is no access to the request, like signals
    """

    def middleware(request):
        # Set the current user in the context
        user = getattr(request, "user", None)
        set_current_user(user if user and user.is_authenticated else None)

        try:
            response = get_response(request)
        finally:
            # Clean up: reset the user context after the request
            set_current_user(None)

        return response

    return middleware
