# pylint: disable=import-error, invalid-name
"""Tests jobs."""

import os

from pytest import mark

from qiskit_serverless import ServerlessClient, QiskitFunction

resources_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "../source_files"
)

filename = "data.tar"
filename_path = os.path.join(resources_path, filename)


class TestExperimental:
    """Test class for integration testing with docker."""

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

        files = serverless_client.files(function)
        print(files)
        assert files is not None

        file_count = len(files)

        assert file_count > 0

        serverless_client.file_delete("my_file.tar", function)

        assert (file_count - len(serverless_client.files(function))) == 1

    def test_list_upload_download_delete(
        self, serverless_client: ServerlessClient, tmp_path
    ):
        """Integration test for upload files."""

        function = QiskitFunction(
            title="hello-world",
            entrypoint="hello_world.py",
            working_dir=resources_path,
        )
        serverless_client.upload(function)

        function = serverless_client.function("hello-world")

        print(serverless_client.file_upload(filename_path, function))
        files = serverless_client.files(function)
        print(files)

        assert filename in files

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        assert (
            serverless_client.file_download(
                filename, function, download_location=str(download_dir)
            )
            is not None
        )

        print(serverless_client.file_delete(filename, function))
        files = serverless_client.files(function)
        print(files)

        assert filename not in files

    def test_list_upload_download_delete_with_provider_function(
        self, serverless_client: ServerlessClient, tmp_path
    ):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test-local-provider-function:latest",
        )
        serverless_client.upload(function)

        function = serverless_client.function("mockprovider/provider-function")

        print(serverless_client.file_upload(filename_path, function))
        files = serverless_client.files(function)
        print(files)

        assert filename in files

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        assert (
            serverless_client.file_download(
                filename, function, download_location=str(download_dir)
            )
            is not None
        )

        print(serverless_client.file_delete(filename, function))
        files = serverless_client.files(function)
        print(files)

        assert filename not in files

    def test_provider_list_upload_download_delete(
        self, serverless_client: ServerlessClient, tmp_path
    ):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test-local-provider-function:latest",
        )
        serverless_client.upload(function)

        function = serverless_client.function("mockprovider/provider-function")

        print(serverless_client.provider_file_upload(filename_path, function))
        files = serverless_client.provider_files(function)
        print(files)

        assert filename in files

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        assert (
            serverless_client.provider_file_download(
                filename, function, download_location=str(download_dir)
            )
            is not None
        )

        print(serverless_client.provider_file_delete(filename, function))
        files = serverless_client.provider_files(function)
        print(files)

        assert filename not in files
