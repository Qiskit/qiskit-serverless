"""
Specific router for QiskitServerless project
"""

from rest_framework.routers import SimpleRouter


class QiskitServerlessRouter(SimpleRouter):
    """
    This Router overwrites the default functionality for DRF
    SimpleRouter allowing to do calls with and without slashes:
    - /api/v1/programs
    - /api/v1/programs/
    """

    def __init__(self):
        super().__init__(trailing_slash="/?")  # Optional slash
