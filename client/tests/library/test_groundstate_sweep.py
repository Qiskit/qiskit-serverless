"""Test groundstate sweep."""

from unittest import TestCase

from quantum_serverless import QuantumServerless
from quantum_serverless.library.groundstate_sweep import (
    groundstate_solver_parallel_sweep,
    SweepResult,
)


class TestGroundStateSweep(TestCase):
    """TestGroundStateSweep."""

    def test_sweep(self):
        """Tests function."""
        serverless = QuantumServerless()

        with serverless:
            results = groundstate_solver_parallel_sweep(
                molecules=[["H", "H"], ["H", "H"], ["H", "H"]]
            )
            self.assertEqual(len(results), 3)
            self.assertIsInstance(results[0], SweepResult)
