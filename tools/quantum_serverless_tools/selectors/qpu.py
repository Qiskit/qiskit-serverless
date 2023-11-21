"""QPU selector module."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any

import mapomatic as mm
from qiskit import transpile, QuantumCircuit
from qiskit_ibm_runtime import Session, QiskitRuntimeService
from qiskit_ibm_runtime.ibm_backend import IBMBackend


class IBMQPUSelector(ABC):
    """Base class for IBM QPU selector implementations."""

    def __init__(
        self,
        service: QiskitRuntimeService | str,
        **context: Dict[str, Any],
    ):
        """
        Initialize an IBMQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service client or token
            context: Additional keyword arguments needed to contextualize QPU selection
        """
        if isinstance(service, str):
            runtime_service = QiskitRuntimeService(channel="ibm_quantum", token=service)
        else:
            runtime_service = service
        self._service = runtime_service

    @abstractmethod
    def get_backend(self, **filters: dict[str, Any]) -> IBMBackend:
        """
        Select the best backend with respect to the given context.

        Args:
            filters: Criteria for filtering out backends from selection

        Returns:
            A backend object which fits the specified context
        """
        pass

    @abstractmethod
    def get_session(self, **filters: dict[str, Any]) -> Session:
        """
        Return a session for the best backend with respect to the given context.

        Args:
            filters: Criteria for filtering out backends from selection

        Returns:
            A backend session object which fits the specified context.
        """
        pass


class IBMLeastBusyQPUSelector(IBMQPUSelector):
    """QPU selector for choosing the least busy IBM backend."""

    def __init__(self, service: QiskitRuntimeService | str):
        """
        Initialize an IBMLeastBusyQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service client or token
        """
        super().__init__(service)

    def get_backend(self, *, min_num_qubits: int) -> IBMBackend:
        """
        Get the backend with the fewest number of pending jobs.

        Args:
          min_num_qubits: The number of qubits required of the QPU

        Returns:
            The backend with the fewest number of pending jobs which fits the
            specified context.
        """
        return _get_least_busy_qpu(min_num_qubits, self._service)

    def get_session(self, *, min_num_qubits: int) -> Session:
        """
        Get a session for the least busy backend.

        Args:
            min_num_qubits: The number of qubits required of the QPU

        Returns:
            A backend session for the least busy backend.
        """
        return Session(backend=_get_least_busy_qpu(min_num_qubits, self._service))


class IBMLeastNoisyQPUSelector(IBMQPUSelector):
    """
    QPU selector for choosing the least noisy backend for a given circuit.

    Document this more thoroughly. Include links to the VF2 algorithms leveraged.
    """

    def __init__(
        self,
        service: QiskitRuntimeService | str,
        *,
        circuit: QuantumCircuit,
    ):
        """
        Initialize an IBMLeastNoisyQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service client or token
            circuit: A circuit for which to select optimal qubits
        """
        super().__init__(service)
        self._circuit = circuit

    def get_backend(self, *, min_num_qubits: int | None = None) -> IBMBackend:
        """
        Get the backend which produces the least noisy qubit mapping for the given circuit.

        Args:
            min_num_qubits: The number of qubits required of the QPU. If ``None``, the number
                of qubits in the input circuit will be used.

        Returns:
            The backend which produces the least noisy qubit mapping for the given circuit
        """
        if min_num_qubits is None:
            min_num_qubits = self._circuit.num_qubits

        return _get_least_noisy_qpu(min_num_qubits, self._service, self._circuit)

    def get_session(self, *, min_num_qubits: int | None = None) -> Session:
        """
        Get a session for the least noisy backend.

        Args:
            min_num_qubits: The number of qubits required of the QPU. If ``None``, the number
                of qubits in the input circuit will be used.

        Returns:
            A session for the least noisy backend
        """
        if min_num_qubits is None:
            min_num_qubits = self._circuit.num_qubits

        return Session(
            backend=_get_least_noisy_qpu(min_num_qubits, self._service, self._circuit)
        )


def _get_least_noisy_qpu(
    min_num_qubits: int, service: QiskitRuntimeService, circuit: QuantumCircuit
) -> IBMBackend:
    """Get the least noisy backend. Filter all simulators and inactive devices."""

    # qiskit-ibm-runtime Issue #1136 submitted to address bug causing
    # stabilizer simulator to crash when their "simulator" property is
    # invoked. Until this is fixed, we will filter out those backends by
    # removing backends prefixed with "simulator_".
    #
    # https://github.com/Qiskit/qiskit-ibm-runtime/issues/1136
    backends = service.backends(
        min_num_qubits=min_num_qubits,
        filters=lambda b: b.name.split("_")[0] != "simulator"
        and not b.simulator
        and b.status().status_msg == "active"
        and b.status().operational,
    )
    assert len(backends) > 0

    # Get a transpiled circuit, including additional SWAP gates and ancillas.
    trans_qc = transpile(circuit, backends[0], optimization_level=3)

    # Deflate the circuit to just the number of active qubits
    small_qc = mm.deflate_circuit(trans_qc)

    # Return the backend with the best noise profile wrt the input circuit
    return service.get_backend(mm.best_overall_layout(small_qc, backends)[1])


def _get_least_busy_qpu(
    min_num_qubits: int, service: QiskitRuntimeService
) -> IBMBackend:
    """Get the least busy backend. Filter all simulators and inactive devices."""

    # qiskit-ibm-runtime Issue #1136 submitted to address bug causing
    # stabilizer simulator to crash when their "simulator" property is
    # invoked. Until this is fixed, we will filter out those backends by
    # removing backends prefixed with "simulator_".
    #
    # https://github.com/Qiskit/qiskit-ibm-runtime/issues/1136
    return service.least_busy(
        min_num_qubits=min_num_qubits,
        filters=lambda b: b.name.split("_")[0] != "simulator"
        and not b.simulator
        and b.status().status_msg == "active"
        and b.status().operational,
    )
