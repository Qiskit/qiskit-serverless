"""Tests primitives."""

from unittest import TestCase, skip

from qiskit import QuantumCircuit
from qiskit.circuit.library import RealAmplitudes
from qiskit.quantum_info import SparsePauliOp
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    Session,
    Options,
    EstimatorResult,
    SamplerResult,
)

from quantum_serverless import QuantumServerless
from quantum_serverless.library.primitives import ParallelEstimator, ParallelSampler


class TestPrimitives(TestCase):
    """TestPrimitives."""

    @skip("Require IBM Cloud account.")
    def test_parallel_estimator(self):
        """Test parallel estimator."""
        serverless = QuantumServerless()

        service = QiskitRuntimeService()
        options = Options(optimization_level=1, backend="ibmq_qasm_simulator")

        options.execution.shots = 10
        psi1 = RealAmplitudes(num_qubits=2, reps=2)
        obs = SparsePauliOp.from_list([("II", 1), ("IZ", 2), ("XI", 3)])
        theta1 = [0, 1, 1, 2, 3, 5]

        with Session(service=service) as session, serverless.context():
            estimator = ParallelEstimator(session=session, options=options)

            estimator.add(circuits=[psi1], observables=[obs], parameter_values=[theta1])
            estimator.add(circuits=[psi1], observables=[obs], parameter_values=[theta1])
            estimator.add(circuits=[psi1], observables=[obs], parameter_values=[theta1])

            results = estimator.run_all()
            self.assertEqual(len(results), 3)
            for result in results:
                self.assertIsInstance(result, EstimatorResult)

    @skip("Require IBM Cloud account.")
    def test_parallel_sampler(self):
        """Test parallel estimator."""
        serverless = QuantumServerless()

        service = QiskitRuntimeService()
        options = Options(optimization_level=1, backend="ibmq_qasm_simulator")
        options.execution.shots = 10

        bell = QuantumCircuit(2)
        bell.h(0)
        bell.cx(0, 1)
        bell.measure_all()

        with Session(service=service) as session, serverless.context():
            sampler = ParallelSampler(session=session, options=options)

            sampler.add(circuits=bell)
            sampler.add(circuits=bell)
            sampler.add(circuits=bell)
            sampler.add(circuits=bell)

            results = sampler.run_all()
            self.assertEqual(len(results), 4)
            for result in results:
                self.assertIsInstance(result, SamplerResult)
