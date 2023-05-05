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
Serializers (:mod:`quantum_serverless.serializers.program_serializers`)
=======================================================================

.. currentmodule:: quantum_serverless.serializers.program_serializers

Quantum serverless program serializers
======================================

.. autosummary::
    :toctree: ../stubs/

    QiskitObjectsDecoder
    QiskitObjectsEncoder
"""
import json
import os
from typing import Any, Dict

from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_ibm_runtime.utils.json import RuntimeDecoder, RuntimeEncoder

from quantum_serverless.core.constants import ENV_JOB_ARGUMENTS


class QiskitObjectsEncoder(RuntimeEncoder):
    """Json encoder for Qiskit objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, QiskitRuntimeService):
            return {
                "__type__": "QiskitRuntimeService",
                "__value__": obj.active_account(),
            }
        return super().default(obj)


class QiskitObjectsDecoder(RuntimeDecoder):
    """Json decoder for Qiskit objects."""

    def object_hook(self, obj: Any) -> Any:
        if "__type__" in obj:
            obj_type = obj["__type__"]

            if obj_type == "QiskitRuntimeService":
                return QiskitRuntimeService(**obj["__value__"])
            return super().object_hook(obj)
        return obj


def get_arguments() -> Dict[str, Any]:
    """Parses arguments for program and returns them as dict.

    Returns:
        Dictionary of arguments.
    """
    return json.loads(os.environ.get(ENV_JOB_ARGUMENTS, "{}"), cls=QiskitObjectsDecoder)
