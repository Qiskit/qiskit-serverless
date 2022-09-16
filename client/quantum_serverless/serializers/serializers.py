"""Serializers."""
import base64
import io

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
