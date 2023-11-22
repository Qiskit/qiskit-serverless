# This code is a Qiskit project.

# (C) Copyright IBM 2023.

# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""QPU selector module."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Callable

import mapomatic as mm
from qiskit import transpile, QuantumCircuit
from qiskit_ibm_runtime import QiskitRuntimeService, IBMBackend


class IBMQPUSelector(ABC):
    """Base class for IBM QPU selector implementations."""

    def __init__(
        self,
        service: QiskitRuntimeService | dict[str, str],
        **context,
    ):
        """
        Initialize an IBMQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service. This may be a ``QiskitRuntimeService``
                instance or a dictionary specifying the account information. See the
                [QiskitRuntimeService.active_account](https://docs.quantum-computing.ibm.com/api/qiskit-ibm-runtime/qiskit_ibm_runtime.QiskitRuntimeService#active_account) method for more details.

            context: Additional keyword arguments needed to contextualize QPU selection
        """
        if isinstance(service, dict):
            runtime_service = QiskitRuntimeService(**service)
        else:
            runtime_service = service
        self._service = runtime_service

    @abstractmethod
    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[list[IBMBackend]], bool]] = None,
        **kwargs,
    ) -> IBMBackend:
        """
        Select the best backend with respect to the given context.

        Args:
            min_num_qubits: Minimum number of qubits the backend has to have
            instance: hub/group/project from which to select backend
            filters: More complex filters, such as lambda functions.
                Examples::

                    IBMQPUSelector.get_backend(filters=lambda b: b.max_shots > 50000)
                    IBMQPUSelector.get_backend(filters=lambda x: ("rz" in x.basis_gates)

            **kwargs: Simple filters that require a specific value for an attribute in
                backend configuration or status.
                Example::

                    # Get the backends that support OpenPulse
                    IBMQPUSelector.get_backend(open_pulse=True)

                For the full list of backend attributes, see the `IBMBackend` class documentation
                <https://qiskit.org/documentation/apidoc/providers_models.html>

        Returns:
            A backend object which fits the specified context
        """


class IBMLeastBusyQPUSelector(IBMQPUSelector):
    """QPU selector for choosing the least busy IBM backend."""

    def __init__(self, service: QiskitRuntimeService | dict[str, str]):
        """Initialize an IBMLeastBusyQPUSelector instance."""
        super().__init__(service)

    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[list[IBMBackend]], bool]] = None,
        **kwargs,
    ) -> IBMBackend:
        """
        Get the backend with the fewest number of pending jobs.

        See superclass for detailed documentation.
        """
        return _get_least_busy_qpu(
            self._service,
            min_num_qubits=min_num_qubits,
            instance=instance,
            filters=filters,
            **kwargs,
        )


class IBMLeastNoisyQPUSelector(IBMQPUSelector):
    """
    QPU selector for choosing the least noisy backend for a given circuit.

    Document this more thoroughly. Include links to the VF2 algorithms leveraged.
    """

    def __init__(
        self,
        service: QiskitRuntimeService | dict[str, str],
        *,
        circuit: QuantumCircuit,
        transpile_options: Optional[dict[str, Any]] = None,
    ):
        """
        Initialize an IBMLeastNoisyQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service client or token
            circuit: The circuit for which the least noisy qubit mapping will be selected
            transpile_options: Options to Qiskit's ``transpile`` function. Used to
                determine the best backend for which to optimize the input circuit.
        """
        super().__init__(service)
        self._circuit = circuit
        self._transpile_options = transpile_options
        self._optimized_circuit = None

    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[list[IBMBackend]], bool]] = None,
        **kwargs,
    ) -> IBMBackend:
        """
        Get the backend which produces the least noisy qubit mapping for the given circuit.

        See superclass for detailed documentation.

        Returns:
            The backend which produces the least noisy qubit mapping for the given circuit.
        """
        if min_num_qubits is None or min_num_qubits < self._circuit.num_qubits:
            min_num_qubits = self._circuit.num_qubits

        backend, self._optimized_circuit = _get_least_noisy_qpu(
            self._service,
            self._circuit,
            transpile_options=self._transpile_options,
            min_num_qubits=min_num_qubits,
            instance=instance,
            filters=filters,
            **kwargs,
        )

        return backend

    @property
    def optimized_circuit(self) -> Optional[QuantumCircuit]:
        """
        Get a circuit which has been optimized for the selected backend.

        If no backend has been selected yet, this property will be ``None``.
        Use the :meth:`get_backend` method to generate a circuit which has
        been optimized for backend execution.
        """
        return self._optimized_circuit


def _get_least_noisy_qpu(
    service: QiskitRuntimeService,
    circuit: QuantumCircuit,
    transpile_options: Optional[dict[str, Any]],
    min_num_qubits: Optional[int] = None,
    instance: Optional[str] = None,
    filters: Optional[Callable[[list[IBMBackend]], bool]] = None,
    **kwargs,
) -> tuple[IBMBackend, QuantumCircuit]:
    """Get the least noisy backend. Filter all simulators and inactive devices."""
    kwargs["operational"] = True
    kwargs["simulator"] = False
    backends = service.backends(
        min_num_qubits=min_num_qubits,
        instance=instance,
        filters=filters,
        **kwargs,
    )

    # Get a transpiled circuit, including additional SWAP gates and ancillas.
    transpile_options["backend"] = backends[0]
    trans_qc = transpile(circuits=circuit, **transpile_options)

    # Deflate the circuit to just the number of active qubits
    small_qc = mm.deflate_circuit(trans_qc)

    # Save the optimized circuit, which has been transpiled to the most optimal backend
    best_ovr_layout = mm.best_overall_layout(small_qc, backends)
    backend = service.get_backend(best_ovr_layout[1])
    best_layout = best_ovr_layout[0]

    transpile_options["initial_layout"] = best_layout
    transpile_options["backend"] = backend
    optimal_circuit = transpile(circuits=small_qc, **transpile_options)

    return backend, optimal_circuit


def _get_least_busy_qpu(
    service: QiskitRuntimeService,
    min_num_qubits: Optional[int] = None,
    instance: Optional[str] = None,
    filters: Optional[Callable[[list[IBMBackend]], bool]] = None,
    **kwargs,
) -> IBMBackend:
    """Get the least busy backend. Filter all simulators and inactive devices."""
    return service.least_busy(
        min_num_qubits=min_num_qubits,
        instance=instance,
        filters=filters,
        **kwargs,
    )
