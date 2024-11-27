# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os
import tarfile

from pytest import fixture, mark
from testcontainers.compose import DockerCompose

from qiskit_serverless import ServerlessClient, QiskitFunction

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "./source_files"
)


class TestDockerExperimental:
    """Test class for integration testing with docker."""

    @fixture(scope="class")
    def serverless_client(self):
        """Fixture for testing files."""
        compose = DockerCompose(
            resources_path,
            compose_file_name="../../../docker-compose-dev.yaml",
            pull=True,
        )
        compose.start()

        connection_url = "http://localhost:8000"
        compose.wait_for(f"{connection_url}/backoffice")

        serverless = ServerlessClient(
            token=os.environ.get("GATEWAY_TOKEN", "awesome_token"),
            host=os.environ.get("GATEWAY_HOST", connection_url),
        )
        yield serverless

        compose.stop()

    @mark.skip(reason="Speeding up testing with github jobs: delete before merge")
    def test_file_download(self, serverless_client: ServerlessClient):
        """Integration test for files."""

        function = QiskitFunction(
            title="file-producer-for-download",
            entrypoint="produce_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        function = serverless_client.function("file-producer-for-download")
        job = function.run()
        assert job is not None

        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        print("::: JOB LOGS :::")
        print(job.logs())
        print("::: JOB RESULT :::")
        print(job.result())

        available_files = serverless_client.files()
        assert available_files is not None
        assert len(available_files) > 0

        assert serverless_client.file_download(available_files[0]) is not None

    @mark.skip(reason="Speeding up testing with github jobs: delete before merge")
    @mark.order(1)
    def test_file_producer(self, serverless_client: ServerlessClient):
        """Integration test for files."""
        filename = "uploaded_file.tar"
        with tarfile.open(filename, "w") as file:
            file.add(f"{resources_path}/../manage_data_directory.py")

        serverless_client.file_upload(filename)

        function = QiskitFunction(
            title="file-producer-for-consume",
            entrypoint="produce_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        file_producer_function = serverless_client.function("file-producer-for-consume")

        job = file_producer_function.run()

        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        assert len(serverless_client.files()) > 0

    @mark.skip(reason="Speeding up testing with github jobs: delete before merge")
    @mark.order(2)
    def test_file_consumer(self, serverless_client: ServerlessClient):
        """Integration test for files."""
        function = QiskitFunction(
            title="file-consumer",
            entrypoint="consume_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        file_consumer_function = serverless_client.function("file-consumer")

        job = file_consumer_function.run()
        assert job is not None
        assert job.result() is not None
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        files = serverless_client.files()

        assert files is not None

        file_count = len(files)

        assert file_count > 0

        serverless_client.file_delete("uploaded_file.tar")

        assert (file_count - len(serverless_client.files())) == 1

    def test_simple(self, serverless_client: ServerlessClient):
        """Integration test for files."""

        function = QiskitFunction(
            title="file-consumer",
            entrypoint="consume_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        filename = f"{resources_path}/data.tar"

        print("::: file_upload :::")
        print(serverless_client.file_upload(filename))

        files = serverless_client.files()
        print("::: files :::")
        print(files)

        assert files is not None

        file_count = len(files)
        print("::: file_count :::")
        print(file_count)

        assert file_count > 0

        print("::: file_delete :::")
        print(serverless_client.file_delete(filename))

        print("::: files :::")
        print(serverless_client.files())

        assert (file_count - len(serverless_client.files())) == 1
