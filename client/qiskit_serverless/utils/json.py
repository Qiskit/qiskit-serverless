# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
=====================================================
Json utilities (:mod:`qiskit_serverless.utils.json`)
=====================================================

.. currentmodule:: qiskit_serverless.utils.json

Qiskit Serverless json utilities
=================================

.. autosummary::
    :toctree: ../stubs/

    JsonSerializable
"""

import json
from abc import ABC, abstractmethod
from json import JSONEncoder
from typing import List, Optional, Type, Callable, Dict, Any, Union

import requests

from qiskit_serverless.exception import QiskitServerlessException
from qiskit_serverless.utils.errors import format_err_msg, ErrorCodes


class JsonSerializable(ABC):
    """Classes that can be serialized as json."""

    @classmethod
    @abstractmethod
    def from_dict(cls, dictionary: dict):
        """Converts dict to object."""

    def to_dict(self) -> dict:
        """Converts class to dict."""
        result = {}
        for key, val in self.__dict__.items():
            if key.startswith("_"):
                continue
            element = []
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, JsonSerializable):
                        element.append(item.to_dict())
                    else:
                        element.append(item)
            elif isinstance(val, JsonSerializable):
                element = val.to_dict()  # type: ignore
            else:
                element = val
            result[key] = element
        return result


def is_jsonable(data, cls: Optional[Type[JSONEncoder]] = None):
    """Check if data can be serialized to json."""
    try:
        json.dumps(data, cls=cls)
        return True
    except (TypeError, OverflowError):
        return False


_MAX_BODY_SNIPPET_LEN = 500


def _body_snippet(text: Optional[str]) -> str:
    """Condenses a non-JSON response body into a short, readable snippet.

    Intermediaries (Cloudflare, proxies, load balancers) may return large HTML
    error pages. This collapses whitespace and truncates so the message stays
    readable while preserving enough of the body to identify the source.

    Args:
        text: raw response body.

    Returns:
        a single-line, length-capped snippet (empty-body note if blank).
    """
    if not text or not text.strip():
        return "(empty response body)"
    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_BODY_SNIPPET_LEN:
        collapsed = collapsed[:_MAX_BODY_SNIPPET_LEN] + "..."
    return collapsed


def raise_for_non_ok_response(response: requests.Response) -> None:
    """Raise a readable exception if the response is not OK.

    Surfaces the HTTP status and a snippet of the body so that a block page or
    error body from an intermediary (Cloudflare, proxy, load balancer) or from
    COS itself is reported clearly, instead of being fed to a JSON parser and
    surfacing a cryptic decoding error. If the body is JSON, its values are
    included; otherwise a cleaned text snippet is used.

    Args:
        response: the HTTP response to check.

    Raises:
        QiskitServerlessException: if ``response`` is not OK.
    """
    if response is None or response.ok:
        return
    try:
        json_data = json.loads(response.text)
        details = "".join(str(value) for value in json_data.values()) if isinstance(json_data, Dict) else str(json_data)
    except json.JSONDecodeError:
        details = _body_snippet(response.text)
    raise QiskitServerlessException(
        format_err_msg(
            response.status_code,
            details,
        )
    )


def safe_json_request_as_list(request: Callable[..., requests.Response]) -> List[Any]:
    """Returns parsed json data from request.

    Args:
        request: callable for request.

    Example:
        >>> safe_json_request(request=lambda: requests.get("https://ibm.com"))

    Returns:
        parsed json response as list structure
    """
    response = safe_json_request(request)
    if isinstance(response, List):
        return response
    raise TypeError("JSON is not a List")


def safe_json_request_as_dict(
    request: Callable[..., requests.Response],
) -> Dict[str, Any]:
    """Returns parsed json data from request.

    Args:
        request: callable for request.

    Example:
        >>> safe_json_request(request=lambda: requests.get("https://ibm.com"))

    Returns:
        parsed json response as dict structure
    """
    response = safe_json_request(request)
    if isinstance(response, Dict):
        return response
    raise TypeError("JSON is not a Dict")


def safe_json_request(
    request: Callable[..., requests.Response],
) -> Union[Dict[str, Any], List[Any]]:
    """Returns parsed json data from request.

    Args:
        request: callable for request.

    Example:
        >>> safe_json_request(request=lambda: requests.get("https://ibm.com"))

    Returns:
        parsed json response
    """
    error_message: Optional[str] = None
    try:
        response = request()
    except requests.exceptions.RequestException as request_exception:
        error_message = format_err_msg(
            ErrorCodes.AUTH1001,
            str(request_exception.args),
        )

    if error_message:
        raise QiskitServerlessException(error_message)

    try:
        json_data = json.loads(response.text)
    except json.JSONDecodeError as json_error:
        # The body is not JSON. This commonly happens when an intermediary
        # (Cloudflare, an ingress/proxy, a load balancer) returns an HTML
        # error page or an empty body instead of the gateway's JSON. Surface
        # the HTTP status and a snippet of the body so the real cause is
        # visible, rather than a bare JSON1001 that hides it.
        if response is not None and not response.ok:
            raise QiskitServerlessException(
                format_err_msg(
                    response.status_code,
                    _body_snippet(response.text),
                )
            ) from json_error
        # A successful (2xx) response whose body we cannot decode is a genuine
        # violation of the server contract: report it as a JSON decoding error.
        raise QiskitServerlessException(
            format_err_msg(
                ErrorCodes.JSON1001,
                str(json_error.args),
            )
        ) from json_error

    if response is not None and not response.ok:
        # When response is not ok, the expected json
        # response is a dictionary with a field
        # that contains the error message. The key
        # varies between messages, so appending all
        # values to a string allows to capture all
        # potential messages.
        error_msg = ""
        for error_string in json_data.values():
            error_msg += str(error_string)

        raise QiskitServerlessException(
            format_err_msg(
                response.status_code,
                str(error_msg),
            )
        )

    return json_data
