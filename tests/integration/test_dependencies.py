# pylint: disable=import-error, invalid-name
"""Tests dependencies."""

import os

from pytest import raises

from qiskit_serverless import (
    QiskitFunction,
    ServerlessClient,
    QiskitServerlessException,
)

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)


class TestDependencies:
    """Test class for integration testing dependencies."""

    def test_function_dependencies_basic(self, serverless_client: ServerlessClient):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-1",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum"],
        )

        runnable_function = serverless_client.upload(function)

        job = runnable_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.result() == {"hours": 3}
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

    def test_function_dependencies_with_version(
        self, serverless_client: ServerlessClient
    ):
        """Integration test for Functions with dependencies."""
        function = QiskitFunction(
            title="pattern-with-dependencies-2",
            entrypoint="pattern_with_dependencies.py",
            working_dir=resources_path,
            dependencies=["pendulum==3.0.0"],
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

        assert deps == ["pendulum>=3.0.0", "wheel>=0.45.1"]
