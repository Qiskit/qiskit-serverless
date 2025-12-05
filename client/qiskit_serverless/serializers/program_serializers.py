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
from qiskit_ibm_runtime.utils.json import RuntimeDecoder, RuntimeEncoder

from qiskit_serverless.core.config import Config
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

            if obj_type == "QiskitRuntimeService":
                return QiskitRuntimeService(**obj["__value__"])
            if obj_type == "SamplerResult":
                return SamplerResult(**obj["__value__"])
            if obj_type == "EstimatorResult":
                return EstimatorResult(**obj["__value__"])
            return super().object_hook(obj)
        return obj


def get_arguments() -> Dict[str, Any]:
    """Parses arguments for program and returns them as dict.
    Returns:
        Dictionary of arguments.
    """
    arguments = "{}"
    job_id_gateway = Config.job_id_gateway()
    if not job_id_gateway:
        raise QiskitServerlessException(
            "Error getting arguments: JOB_ID_GATEWAY environment variable is missing or empty"
        )
    # DATA_PATH is just used in tests and local development.
    # In k8 we always want to use the default "/data"
    data_path = Config.data_path()
    arguments_dir = f"{data_path}/arguments"
    arguments_file_path = f"{arguments_dir}/{job_id_gateway}.json"

    os.makedirs(arguments_dir, exist_ok=True)

    if not os.path.isfile(arguments_file_path):
        raise QiskitServerlessException(
            f"Error getting arguments: {arguments_file_path} is not a file or doesn't exists"
        )

    with open(arguments_file_path, "r", encoding="utf-8") as f:
        arguments = f.read()

    return json.loads(arguments, cls=QiskitObjectsDecoder)
