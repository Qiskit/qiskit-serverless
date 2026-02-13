"""
Endpoint decorator Module
"""

import logging
from functools import wraps
from typing import Callable

from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import status

from api.domain.exceptions.not_found_error import NotFoundError
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.forbidden_error import ForbiddenError

logger = logging.getLogger("gateway")


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
        except ValidationError as error:
            return Response(
                {"message": _first_error_message(error.detail)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ActiveJobLimitExceeded as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error(
                "Unexpected error occurred in view: %s",
                str(error),
            )
            return Response(
                {"message": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    return wrapped_view
