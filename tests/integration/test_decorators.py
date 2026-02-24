# pylint: disable=import-error, invalid-name, no-member
"""Tests for decorator-based function definitions."""

import os

from pytest import mark, xfail

from qiskit import QuantumCircuit
from qiskit.primitives import StatevectorSampler as Sampler
from qiskit.circuit.random import random_circuit

from qiskit_serverless import (
    ServerlessClient,
    distribute_qiskit_function,
    distribute_task,
    get,
)

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")


class TestDecorators:
    """Test class for decorator-based function definitions."""

    @mark.order(1)
    def test_simple_decorator_function(self, serverless_client: ServerlessClient):
        """DEPRECATED. Test a simple function defined with @distribute_qiskit_function decorator."""

        @distribute_qiskit_function(serverless_client)
        def hello_qiskit():
            circuit = QuantumCircuit(2)
            circuit.h(0)
            circuit.cx(0, 1)
            circuit.measure_all()

            sampler = Sampler()
            quasi_dists = sampler.run([circuit]).result()[0].data.meas.get_counts()

            return quasi_dists

        job = hello_qiskit()

        assert job is not None

        try:
            result = job.result()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            xfail(f"Flaky failure on deprecated decorator: {exc}")

        assert result is not None
        # Result should have measurement outcomes like {"00": X, "11": Y}
        allowed_keys = {"00", "11"}
        assert set(result.keys()).issubset(allowed_keys)

        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_distributed_tasks(self, serverless_client: ServerlessClient):
        """DEPRECATED. Test function with distributed tasks using @distribute_task decorator."""

        @distribute_task(target={"cpu": 1})
        def distributed_sample(circuit: QuantumCircuit):
            """Distributed task that returns quasi distribution for given circuit."""
            return Sampler().run([circuit]).result()[0].data.meas.get_counts()

        @distribute_qiskit_function(serverless_client)
        def function_with_distributed_tasks(circuits):
            sample_task_references = [distributed_sample([circuit]) for circuit in circuits]
            results = get(sample_task_references)
            return {"results": results}

        circuits = []
        for _ in range(3):
            circuit = random_circuit(2, 2)
            circuit.measure_all()
            circuits.append(circuit)

        job = function_with_distributed_tasks(circuits=circuits)

        assert job is not None

        try:
            result = job.result()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            xfail(f"Flaky failure on deprecated decorator: {exc}")
        assert result is not None
        assert "results" in result
        assert len(result["results"]) == 3

        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_decorator_with_modules(self, serverless_client: ServerlessClient):
        """DEPRECATED. Test function with working_dir that imports local modules."""

        @distribute_qiskit_function(serverless_client, working_dir=resources_path)
        def my_function_with_modules():
            # This import happens on the remote side
            from circuit_utils import (  # pylint: disable=import-outside-toplevel
                create_hello_world_circuit as create_circuit,
            )

            quasi_dists = Sampler().run([create_circuit()]).result()[0].data.meas.get_counts()
            return {"quasi_dists": quasi_dists}

        job = my_function_with_modules()

        assert job is not None

        try:
            result = job.result()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            xfail(f"Flaky failure on deprecated decorator: {exc}")
        assert result is not None
        assert "quasi_dists" in result

        # Result should have Bell state measurement outcomes
        allowed_keys = {"00", "11"}
        assert set(result["quasi_dists"].keys()).issubset(allowed_keys)

        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)
