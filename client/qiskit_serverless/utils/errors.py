"""Errors utilities."""

import json
from typing import Optional, Dict, Union

from qiskit_serverless.core.job_event import JobEvent

ErrorCodeType = Union[int, str]


def is_http_standard_error(error_code: ErrorCodeType):
    """Returns true if code is in standard http error codes range."""
    result = False
    if isinstance(error_code, int) and (600 > error_code >= 100):
        result = True
    return result


class ErrorCodes:  # pylint: disable=too-few-public-methods
    """Qiskit Serverless error codes."""

    AUTH1001: str = "AUTH1001"
    JSON1001: str = "JSON1001"
    HTTP_STD_ERROR: str = "HTTP_STD_ERROR"


DEFAULT_ERROR_MESSAGE: str = "Something went wrong."
error_mapping: Dict[ErrorCodeType, str] = {
    ErrorCodes.AUTH1001: "Connection error. Make sure configuration " "(host and auth details) is correct.",
    ErrorCodes.HTTP_STD_ERROR: "Http bad request.",
    ErrorCodes.JSON1001: "Error occurred during decoding server json response.",
}


def format_err_msg(code: ErrorCodeType, details: Optional[str] = None):
    """Formats error message.

    Args:
        code: error code
        details: extra information about error

    Returns:
        formatted string
    """
    message = (
        error_mapping[ErrorCodes.HTTP_STD_ERROR]
        if is_http_standard_error(code)
        else error_mapping.get(code, DEFAULT_ERROR_MESSAGE)
    )

    result = f"\n| Message: {message}"
    if code:
        result += f"\n| Code: {code}"
    if details:

        result += "\n| Details:"
        details_json = None
        try:
            details_json = json.loads(details)
        except json.JSONDecodeError:
            pass

        if details_json and isinstance(details_json, Dict):
            for key in details_json:
                if len(details_json[key]) > 0:
                    value = details_json[key][0] if isinstance(details_json[key], list) else details_json[key]
                    result += f"\n|   - {key}: {value}"
        else:
            result += f" {details}"

    return result


def format_err_event(error_event: JobEvent) -> str:
    """Formats error event.

    Args:
        error_event (JobEvent): error event

    Returns:
        formatted string
    """

    message = error_event.data["message"]
    code = error_event.data["code"]
    details = error_event.data.get("args")

    result = f"\n| Message: {message}"
    result += f"\n| Code: {code}"

    if details:
        result += "\n| Details:"
        details_json = None
        try:
            details_json = json.loads(details)
        except json.JSONDecodeError:
            pass

        if details_json and isinstance(details_json, Dict):
            for key in details_json:
                if len(details_json[key]) > 0:
                    value = details_json[key][0] if isinstance(details_json[key], list) else details_json[key]
                    result += f"\n|   - {key}: {value}"
        else:
            result += f" {details}"

    return result
