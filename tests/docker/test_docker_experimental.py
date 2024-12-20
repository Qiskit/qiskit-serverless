# pylint: disable=import-error, invalid-name
"""Tests jobs."""
import os

from pytest import mark

from qiskit_serverless import ServerlessClient, QiskitFunction

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "source_files"
)

filename = "data.tar"
filename_path = os.path.join(resources_path, filename)


class TestDockerExperimental:
    """Test class for integration testing with docker."""

    @mark.skip(
        reason="File producing and consuming is not working. Maybe write permissions for functions?"
    )
    @mark.order(1)
    def test_file_producer(self, serverless_client: ServerlessClient):
        """Integration test for files."""
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

    @mark.skip(
        reason="File producing and consuming is not working. Maybe write permissions for functions?"
    )
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

    @mark.order(1)
    def test_upload_download_delete(self, serverless_client: ServerlessClient):
        """Integration test for upload files."""

        print("::: file_upload :::")
        print(serverless_client.file_upload(filename_path))

        files = serverless_client.files()
        print("::: files :::")
        print(files)

        file_count = len(files)
        print("::: file_count :::")
        print(file_count)

        assert file_count == 1

        print("::: file_download :::")
        assert serverless_client.file_download(filename) is not None

        files = serverless_client.files()
        print("::: files after download :::")
        print(files)

        assert file_count == len(files)

        print("::: file_delete :::")
        print(serverless_client.file_delete(filename))

        print("::: files after delete:::")
        files = serverless_client.files()
        print(files)

        assert (file_count - len(files)) == 1
