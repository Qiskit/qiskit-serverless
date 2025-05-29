"""
Custom middleware used by Qiskit Serverless API
"""


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
