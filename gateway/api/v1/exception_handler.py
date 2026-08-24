"""
Endpoint decorator Module
"""

import logging
from functools import wraps
from typing import Callable

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import status

from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.domain.exceptions.function_disabled_exception import FunctionDisabledException
from api.domain.exceptions.invalid_access_exception import InvalidAccessException
from api.domain.exceptions.invalid_arguments_exception import InvalidArgumentsException
from api.domain.exceptions.not_found_exception import NotFoundError
from api.domain.exceptions.runtime_api_exception import RuntimeFunctionsException

logger = logging.getLogger("api.api.v1.exception_handler")


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
    - ValidationError, InvalidArgumentsException -> 400 BAD REQUEST
    - RequestDataTooBig -> 413 REQUEST ENTITY TOO LARGE
    - All other exceptions -> 500 INTERNAL SERVER ERROR
    """

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):  # pylint: disable=too-many-return-statements
        try:
            return view_func(*args, **kwargs)
        except FunctionDisabledException as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_423_LOCKED,
            )
        except NotFoundError as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_404_NOT_FOUND,
            )
        except RuntimeFunctionsException as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_401_UNAUTHORIZED,
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
        except InvalidArgumentsException as error:
            return Response(
                {"message": error.message, "path": error.path},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ActiveJobLimitExceeded as error:
            return Response(
                {"message": error.message},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except RequestDataTooBig:
            # Raised by HttpRequest.body over DATA_UPLOAD_MAX_MEMORY_SIZE, which DRF reaches while
            # parsing, so it fires before the view runs and there is no serializer error to report.
            # The blanket handler below turned it into "Internal server error", which says nothing
            # about a request the caller can fix by sending less at a time.
            limit_mb = settings.MAX_REQUEST_BODY_SIZE_MB
            logger.warning("Request body over the %s MB limit", limit_mb)
            return Response(
                {"message": f"the request body is larger than the maximum of {limit_mb} MB"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
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
