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
Json utilities (:mod:`quantum_serverless.utils.json`)
=====================================================

.. currentmodule:: quantum_serverless.utils.json

Quantum serverless json utilities
=================================

.. autosummary::
    :toctree: ../stubs/

    JsonSerializable
"""
import json
from abc import ABC
from json import JSONEncoder
from typing import Optional, Type, Callable, Dict, Any

import requests

from quantum_serverless.exception import QuantumServerlessException
from quantum_serverless.utils.errors import format_err_msg, ErrorCodes


class JsonSerializable(ABC):
    """Classes that can be serialized as json."""

    @classmethod
    def from_dict(cls, dictionary: dict):
        """Converts dict to object."""
        raise NotImplementedError

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


def safe_json_request(request: Callable, verbose: bool = False) -> Dict[str, Any]:
    """Returns parsed json data from request.

    Args:
        request: callable for request.
        verbose: post reason in error message

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
            str(request_exception.args) if verbose else None,
        )
        response = None

    if error_message:
        raise QuantumServerlessException(error_message)

    if response is not None and not response.ok:
        raise QuantumServerlessException(
            format_err_msg(
                response.status_code,
                str(response.text) if verbose else None,
            )
        )

    decoding_error_message: Optional[str] = None
    try:
        json_data = json.loads(response.text)
    except json.JSONDecodeError as json_error:
        decoding_error_message = format_err_msg(
            ErrorCodes.JSON1001,
            str(json_error.args) if verbose else None,
        )
        json_data = {}

    if decoding_error_message:
        raise QuantumServerlessException(decoding_error_message)

    return json_data
