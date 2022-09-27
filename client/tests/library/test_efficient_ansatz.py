"""Tests for efficient ansatz sweep."""
from unittest import TestCase, skip

from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_nature.drivers import Molecule

from quantum_serverless import QuantumServerless
from quantum_serverless.library.harware_efficient_ansatze import (
    efficient_ansatz_vqe_sweep,
)


class TestEfficientAnsatz(TestCase):
    """TestEfficientAnsatz."""

    @skip("Call to external service.")
    def test_efficient_ansatz(self):
        """Test efficient ansatz."""
        serverless = QuantumServerless()
        service = QiskitRuntimeService()

        with serverless:
            result = efficient_ansatz_vqe_sweep(
                molecules=[
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 1.0])],
                        charge=0,
                        multiplicity=1,
                    ),
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 1.5])],
                        charge=0,
                        multiplicity=1,
                    ),
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("Li", [0.0, 0.0, 2.0])],
                        charge=0,
                        multiplicity=1,
                    ),
                ],
                initial_points=[
                    [0.1, 0.1, 0.1, 0.1],
                    [0.01, 0.01, 0.01, 0.01],
                    [0.001, 0.001, 0.001, 0.001],
                ],
                service=service,
            )
        self.assertEqual(len(result), 3)
