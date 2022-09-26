"""Test groundstate sweep."""

from unittest import TestCase, skip

from qiskit_nature.drivers import Molecule

from quantum_serverless import QuantumServerless
from quantum_serverless.library.groundstate_sweep import (
    groundstate_solver_parallel_sweep,
    SweepResult,
)


class TestGroundStateSweep(TestCase):
    """TestGroundStateSweep."""

    @skip("Require PySCF")
    def test_sweep(self):
        """Tests function."""
        serverless = QuantumServerless()

        with serverless:
            results = groundstate_solver_parallel_sweep(
                molecules=[
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("H", [0.0, 0.0, 0.735])],
                        charge=0,
                        multiplicity=1,
                    ),
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("H", [0.0, 0.0, 0.635])],
                        charge=0,
                        multiplicity=1,
                    ),
                    Molecule(
                        geometry=[("H", [0.0, 0.0, 0.0]), ("H", [0.0, 0.0, 0.535])],
                        charge=0,
                        multiplicity=1,
                    ),
                ]
            )
            self.assertEqual(len(results), 3)
            self.assertIsInstance(results[0], SweepResult)
