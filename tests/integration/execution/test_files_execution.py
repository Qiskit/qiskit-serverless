# pylint: disable=import-error, invalid-name, duplicate-code
"""Tests jobs."""

import os

from pytest import mark

from qiskit_serverless import ServerlessClient, QiskitFunction

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../source_files")

filename = "test.txt"
filename_path = os.path.join(resources_path, filename)
filename_not_valid = "test-img.png"
filename_not_valid_path = os.path.join(resources_path, filename_not_valid)


class TestFilesExecution:
    """Test class for integration tests producing and consuming files"""

    @mark.order(1)
    def test_file_producer(self, serverless_client: ServerlessClient):
        """Integration test for files."""
        functionTitle = "file-producer-for-consume"
        function = QiskitFunction(
            title=functionTitle,
            entrypoint="produce_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        file_producer_function = serverless_client.function(functionTitle)

        job = file_producer_function.run()

        # pylint: disable=duplicate-code
        assert job is not None
        assert job.result() is not None
        assert job.result() == {"Message": "my_file.txt archived into my_file.tar"}
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        assert len(serverless_client.files(file_producer_function)) > 0

    @mark.order(2)
    def test_file_consumer(self, serverless_client: ServerlessClient):
        """Integration test for files."""
        functionTitle = "file-consumer"
        function = QiskitFunction(
            title=functionTitle,
            entrypoint="consume_files.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        file_consumer_function = serverless_client.function(functionTitle)

        job = file_consumer_function.run()
        assert job is not None
        assert job.result()
        assert job.result() == {"Message": "Hello!"}
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        files = serverless_client.files(file_consumer_function)

        assert files is not None

        file_count = len(files)

        assert file_count > 0

        serverless_client.file_delete("my_file.tar", file_consumer_function)

        assert (file_count - len(serverless_client.files(file_consumer_function))) == 1
