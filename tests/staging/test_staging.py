# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os


from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
)

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestFunctionsStaging:
    """Test class for integration testing in staging environment."""

    def test_simple_function(self, serverless_client: ServerlessClient):
        """Integration test for runtime wrapper."""

        function = QiskitFunction(
            title="test-runtime-wrapper",
            entrypoint="pattern_with_runtime_wrapper.py",
            working_dir=resources_path,
            env_vars={
                "QISKIT_IBM_CHANNEL": "ibm_quantum_platform",
                "QISKIT_IBM_TOKEN": os.environ["QISKIT_IBM_TOKEN"],
                "QISKIT_IBM_INSTANCE": os.environ["QISKIT_IBM_INSTANCE"],
            },
        )
        serverless_client.upload(function)
        my_pattern_function = serverless_client.function("test-runtime-wrapper")

        job = my_pattern_function.run()
        result = job.result()

        # sanity check:
        # confirm that test_eagle is found
        backends = result["backends"]
        assert "test_eagle" in backends

        # second sanity check:
        # confirm that job ids exist
        reference_ids = result["results"]
        assert isinstance(reference_ids, list)
        assert len(reference_ids) == 2

        # finally, check runtime jobs:
        job_id = job.job_id
        runtime_job_ids = serverless_client.runtime_jobs(job_id)
        assert isinstance(runtime_job_ids, list)
        assert len(runtime_job_ids) == 2
        for id, ref_id in zip(runtime_job_ids, reference_ids):
            assert isinstance(id, str)
            assert id == ref_id
