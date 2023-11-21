"""QPU selector module."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any

import mapomatic as mm
from qiskit import transpile, QuantumCircuit
from qiskit_ibm_runtime import Session, QiskitRuntimeService, IBMBackend
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
    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[List[IBMBackend]], bool]] = None,
        **kwargs: Any,
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

            **kwargs: Simple filters that require a specific  value for an attribute in
                backend configuration or status.
                Examples::

                    # Get the backends that support OpenPulse
                    IBMQPUSelector.get_backend(open_pulse=True)

                For the full list of backend attributes, see the `IBMBackend` class documentation
                <https://qiskit.org/documentation/apidoc/providers_models.html>

        Returns:
            A backend object which fits the specified context
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

    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[List[IBMBackend]], bool]] = None,
        **kwargs: Any,
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
        service: QiskitRuntimeService | str,
        transpile_options: dict[str, Any],
    ):
        """
        Initialize an IBMLeastNoisyQPUSelector instance.

        Args:
            service: IBM Qiskit Runtime Service client or token
            transpile_options: Options to Qiskit's ``transpile`` function. Used to
                determine the best backend for which to optimize the input circuit.

        Raises:
            ValueError: Transpile options must contain a value for ``circuits``.
        """
        if "circuits" not in transpile_options:
            raise ValueError(
                'Input transpile options must contain a value for "circuits".'
            )
        if not isinstance(transpile_options["circuits"], QuantumCircuit):
            raise ValueError(
                'The "circuits" transpile option must be a QuantumCircuit instance. '
                "Lists of QuantumCircuits are not supported."
            )

        super().__init__(service)
        self._circuit = transpile_options["circuits"]
        self._transpile_options = transpile_options
        self._optimized_circuit = None

    def get_backend(
        self,
        min_num_qubits: Optional[int] = None,
        instance: Optional[str] = None,
        filters: Optional[Callable[[List[IBMBackend]], bool]] = None,
        **kwargs: Any,
    ) -> IBMBackend:
        """
        Get the backend which produces the least noisy qubit mapping for the given circuit.

        See superclass for detailed documentation on input arguments.

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
    filters: Optional[Callable[[List[IBMBackend]], bool]] = None,
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
    transpile_options.setdefault("backend", backends[0])
    trans_qc = transpile(**transpile_options)

    # Deflate the circuit to just the number of active qubits
    small_qc = mm.deflate_circuit(trans_qc)

    # Save the optimized circuit, which has been transpiled to the most optimal backend
    best_ovr_layout = mm.best_overall_layout(small_qc, backends)
    backend = service.get_backend(best_ovr_layout[1])
    best_layout = best_ovr_layout[0]

    transpile_options["initial_layout"] = best_layout
    transpile_options["backend"] = backend
    transpile_options["circuits"] = small_qc
    optimal_circuit = transpile(**transpile_options)

    return backend, optimal_circuit


def _get_least_busy_qpu(
    service: QiskitRuntimeService,
    min_num_qubits: Optional[int] = None,
    instance: Optional[str] = None,
    filters: Optional[Callable[[List[IBMBackend]], bool]] = None,
    **kwargs: Any,
) -> IBMBackend:
    """Get the least busy backend. Filter all simulators and inactive devices."""
    kwargs["operational"] = True
    kwargs["simulator"] = False
    return service.least_busy(
        min_num_qubits=min_num_qubits,
        instance=instance,
        filters=filters,
        **kwargs,
    )
