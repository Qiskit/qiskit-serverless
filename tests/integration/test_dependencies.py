# pylint: disable=import-error, invalid-name
"""Tests dependencies."""

import os

from pytest import raises

from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
    QiskitServerlessException,
)

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")


class TestDependencies:
    """Test class for integration testing dependencies."""

    def test_function_dependencies_basic(self, serverless_client: ServerlessClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-1",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["mergedeep"],
        )

        runnable_function = serverless_client.upload(function)

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.result() == {"merged": {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}}
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_function_dependencies_with_version(self, serverless_client: ServerlessClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-2",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["mergedeep==1.3.4"],
        )

        runnable_function = serverless_client.upload(function)

        assert runnable_function is not None

    def test_function_blocked_dependency(self, serverless_client: ServerlessClient):
        """Integration test for Functions with blocked dependencies."""
        dependency = "notallowedone"
        function = QiskitFunction(
            title="pattern-with-dependencies-3",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=[dependency],
        )

        def exceptionCheck(e: QiskitServerlessException):
            code_index = str(e).find("Code: 400")
            details_index = str(e).find(f"Dependency `{dependency}` is not allowed")
            return code_index > 0 and details_index > 0

        with raises(QiskitServerlessException, check=exceptionCheck):
            serverless_client.upload(function)

    def test_dependencies_versions(self, serverless_client: ServerlessClient):
        """Integration test for run functions multiple times."""

        deps = serverless_client.dependencies_versions()

        assert deps == [
            "ffsim==0.0.60",
            "mergedeep==1.3.4",
            "mthree==3.0.0",
            "pyscf==2.11.0",
            "qiskit-addon-aqc-tensor[quimb-jax]==0.2.0",
            "qiskit-addon-obp==0.3.0",
            "qiskit-addon-sqd==0.12.0",
            "qiskit-addon-utils==0.2.0",
            "qiskit-aer==0.17.2",
        ]
