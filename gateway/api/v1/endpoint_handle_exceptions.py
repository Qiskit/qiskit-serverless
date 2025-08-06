"""
Endpoint decorator Module
"""

from functools import wraps
from typing import Callable

from rest_framework.response import Response
from rest_framework import status

from api.domain.exceptions.not_found_error import NotFoundError


def endpoint_handle_exceptions(view_func: Callable):
    """
    endpoint decorator for handle views exceptions
    """

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        try:
            return view_func(*args, **kwargs)
        except NotFoundError as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_404_NOT_FOUND,
            )

    return wrapped_view
