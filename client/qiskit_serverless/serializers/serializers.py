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
===============================================================
Serializers (:mod:`qiskit_serverless.serializers.serializers`)
===============================================================

.. currentmodule:: qiskit_serverless.serializers.serializers

Qiskit Serverless serializers
==============================

.. autosummary::
    :toctree: ../stubs/

    register_all_serializers
    circuit_serializer
    circuit_deserializer
    service_serializer
    service_deserializer
"""
import base64
import io
import zlib

import ray
from qiskit import QuantumCircuit, qpy
from qiskit_ibm_runtime import QiskitRuntimeService


def circuit_serializer(circuit: QuantumCircuit) -> str:
    """Serializes QuantumCircuit into string.

    Args:
        circuit: Qiskit QuantumCircuit object to serialize

    Returns:
        circuit encoded in string
    """
    buff = io.BytesIO()
    qpy.dump(circuit, buff)
    buff.seek(0)
    serialized_data = buff.read()
    buff.close()
    serialized_data = zlib.compress(serialized_data)
    return base64.standard_b64encode(serialized_data).decode("utf-8")


def circuit_deserializer(encoded_circuit: str) -> QuantumCircuit:
    """Deserialize encoded QuantumCircuit object.

    Args:
        encoded_circuit: encoded circuit

    Returns:
        QuantumCircuit decoded object
    """
    buff = io.BytesIO()
    decoded = base64.standard_b64decode(encoded_circuit)
    decoded = zlib.decompress(decoded)
    buff.write(decoded)
    buff.seek(0)
    orig = qpy.load(buff)
    buff.close()
    return orig[0]


def service_serializer(service: QiskitRuntimeService):
    """Serializes QiskitRuntimeService."""
    return service.active_account()


def service_deserializer(account: dict):
    """Deserializes QiskitRuntimeService.

    Args:
        account: Dict from calling `QiskitRuntimeService.active_account`

    Returns:
        QiskitRuntimeService instance
    """
    return QiskitRuntimeService(**account)


def register_all_serializers():
    """Registers all serializers."""
    # serialization for QiskitRuntimeService
    ray.util.register_serializer(
        QiskitRuntimeService,
        serializer=service_serializer,
        deserializer=service_deserializer,
    )
    # serialization for QuantumCircuit
    ray.util.register_serializer(
        QuantumCircuit, serializer=circuit_serializer, deserializer=circuit_deserializer
    )
