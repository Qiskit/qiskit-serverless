"""
Endpoint decorator Module
"""

from functools import wraps
from typing import Callable

from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import status

from api.domain.exceptions.bad_request import BadRequest
from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.forbidden_error import ForbiddenError


def _first_error_message(detail) -> str:
    """
    Extracts a readable message from ValidationError.detail.
    Falls back to a generic message if detail is empty.
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        return _first_error_message(detail[0])
    if isinstance(detail, dict) and detail:
        first_key = next(iter(detail))
        return _first_error_message(detail[first_key])
    return ""


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
        except ForbiddenError as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_403_FORBIDDEN,
            )
        except BadRequest as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as error:
            return Response(
                {"message": _first_error_message(error.detail)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    return wrapped_view
