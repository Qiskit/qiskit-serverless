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
=======================================================================
Serializers (:mod:`qiskit_serverless.serializers.program_serializers`)
=======================================================================

.. currentmodule:: qiskit_serverless.serializers.program_serializers

Qiskit Serverless program serializers
======================================

.. autosummary::
    :toctree: ../stubs/

    QiskitObjectsDecoder
    QiskitObjectsEncoder
"""

import json
import os
from typing import Any, Dict
from qiskit.primitives import SamplerResult, EstimatorResult
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime import RuntimeDecoder, RuntimeEncoder

from qiskit_serverless.core.constants import ARGUMENTS_PATH
from qiskit_serverless.exception import QiskitServerlessException


class QiskitObjectsEncoder(RuntimeEncoder):
    """Json encoder for Qiskit objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, QiskitRuntimeService):
            return {
                "__type__": "QiskitRuntimeService",
                "__value__": obj.active_account(),
            }
        if isinstance(obj, SamplerResult):
            return {
                "__type__": "SamplerResult",
                "__value__": {"quasi_dists": obj.quasi_dists, "metadata": obj.metadata},
            }
        if isinstance(obj, EstimatorResult):
            return {
                "__type__": "EstimatorResult",
                "__value__": {"values": obj.values, "metadata": obj.metadata},
            }
        return super().default(obj)


class QiskitObjectsDecoder(RuntimeDecoder):
    """Json decoder for Qiskit objects."""

    def object_hook(self, obj: Any) -> Any:
        if "__type__" in obj:
            obj_type = obj["__type__"]

            # Only reconstruct known types, and only from a well-formed mapping
            # of string keys. This prevents a malicious/compromised gateway from
            # splatting an arbitrarily-shaped "__value__" into these
            # constructors (which would otherwise be attacker-controlled kwargs).
            value = obj.get("__value__")

            def _safe_kwargs() -> dict:
                if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
                    raise ValueError(f"Invalid '__value__' payload for type '{obj_type}'.")
                return value

            if obj_type == "QiskitRuntimeService":
                return QiskitRuntimeService(**_safe_kwargs())
            if obj_type == "SamplerResult":
                return SamplerResult(**_safe_kwargs())
            if obj_type == "EstimatorResult":
                return EstimatorResult(**_safe_kwargs())
            return super().object_hook(obj)
        return obj


def get_arguments() -> Dict[str, Any]:
    """Parses arguments for program and returns them as dict.

    Reads the file path specified by the ``ARGUMENTS_PATH`` environment
    variable, which is set by the runner (Ray or Fleets) at job submission.

    Returns:
        Dictionary of arguments.
    """
    arguments_path = os.environ.get(ARGUMENTS_PATH)
    if not arguments_path:
        raise QiskitServerlessException(
            "Error getting arguments: ARGUMENTS_PATH environment variable is missing or empty"
        )

    os.makedirs(os.path.dirname(arguments_path), exist_ok=True)

    if not os.path.isfile(arguments_path):
        raise QiskitServerlessException(f"Error getting arguments: {arguments_path} is not a file or doesn't exist")

    with open(arguments_path, "r", encoding="utf-8") as f:
        arguments = f.read()

    return json.loads(arguments, cls=QiskitObjectsDecoder)
