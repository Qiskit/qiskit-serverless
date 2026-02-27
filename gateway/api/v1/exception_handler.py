"""
Endpoint decorator Module
"""

import logging
from functools import wraps
from typing import Callable

from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import status

from api.domain.exceptions.not_found_exception import NotFoundError
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.active_job_limit_exceeded_exception import (
    ActiveJobLimitExceeded,
)

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
    Decorator to handle exceptions in API endpoints.

    Catches domain exceptions and converts them to appropriate HTTP responses:
    - NotFoundError and subclasses (JobNotFoundException, ProviderNotFoundException,
      FunctionNotFoundException, FileNotFoundException) -> 404 NOT FOUND
    - InvalidAccessException -> 403 FORBIDDEN
    - ValidationError -> 400 BAD REQUEST
    - All other exceptions -> 500 INTERNAL SERVER ERROR
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
        except InvalidAccessException as error:
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
                exc_info=True,
            )
            return Response(
                {"message": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    return wrapped_view
