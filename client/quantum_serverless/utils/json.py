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
from abc import ABC


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
