"""Tests for VQE"""

from unittest import TestCase, skip

from qiskit.algorithms import VQEResult
from qiskit.algorithms.optimizers import SPSA
from qiskit.circuit.library import EfficientSU2
from qiskit.opflow import PauliSumOp
from qiskit_ibm_runtime import (
    Estimator as RuntimeEstimator,
    Session,
    Options,
    QiskitRuntimeService,
)

from quantum_serverless.library import EstimatorVQE


class TestVQE(TestCase):
    """TestVQE."""

    @skip("Call to external API.")
    def test_estimator_vqe_with_runtime_primitives(self):
        """Test VQE with qiskit estimator."""
        operator = PauliSumOp.from_list(
            [("XYII", 1), ("IYZI", 2), ("IIZX", 3), ("XIII", 4), ("IYII", 5)]
        )
        circuit = EfficientSU2(num_qubits=operator.num_qubits, reps=1)
        optimizer = SPSA(maxiter=1)

        service = QiskitRuntimeService()
        options = Options(optimization_level=1, resilience_level=0)

        with Session(service=service, backend="ibmq_qasm_simulator") as session:
            estimator = RuntimeEstimator(session=session, options=options)

            custom_vqe = EstimatorVQE(estimator, circuit, optimizer)
            result = custom_vqe.compute_minimum_eigenvalue(operator)

            self.assertIsInstance(result, VQEResult)
