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

@mark.skip()
class TestDockerExperimental:
    """Test class for integration testing with docker."""

    @mark.skip(
        reason="File producing and consuming is not working. Maybe write permissions for functions?"
    )
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

        assert len(serverless_client.files(functionTitle)) > 0

    @mark.skip(
        reason="File producing and consuming is not working. Maybe write permissions for functions?"
    )
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
        assert job.result() == {"Message": "Hello"}
        assert job.status() == "DONE"
        assert isinstance(job.logs(), str)

        files = serverless_client.files(functionTitle)

        assert files is not None

        file_count = len(files)

        assert file_count > 0

        serverless_client.file_delete("uploaded_file.tar", functionTitle)

        assert (file_count - len(serverless_client.files(functionTitle))) == 1

    @mark.order(1)
    def test_list_upload_download_delete(self, serverless_client: ServerlessClient):
        """Integration test for upload files."""
        function = serverless_client.function("hello-world")

        print("::: file_upload :::")
        print(serverless_client.file_upload(filename_path, function))

        files = serverless_client.files(function)
        print("::: files :::")
        print(files)

        file_count = len(files)
        print("::: file_count :::")
        print(file_count)

        assert file_count == 1

        print("::: file_download :::")
        assert serverless_client.file_download(filename, function) is not None

        files = serverless_client.files(function)
        print("::: files after download :::")
        print(files)

        assert file_count == len(files)

        print("::: file_delete :::")
        print(serverless_client.file_delete(filename, function))

        print("::: files after delete:::")
        files = serverless_client.files(function)
        print(files)

        assert (file_count - len(files)) == 1

    def test_list_upload_download_delete_with_provider_function(
        self, serverless_client: ServerlessClient
    ):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test-local-provider-function:latest",
        )
        serverless_client.upload(function)

        function = serverless_client.function("mockprovider/provider-function")

        print("::: file_upload :::")
        print(serverless_client.file_upload(filename_path, function))

        files = serverless_client.files(function)
        print("::: files :::")
        print(files)

        file_count = len(files)
        print("::: file_count :::")
        print(file_count)

        assert file_count == 1

        print("::: file_download :::")
        assert serverless_client.file_download(filename, function) is not None

        files = serverless_client.files(function)
        print("::: files after download :::")
        print(files)

        assert file_count == len(files)

        print("::: file_delete :::")
        print(serverless_client.file_delete(filename, function))

        print("::: files after delete:::")
        files = serverless_client.files(function)
        print(files)

        assert (file_count - len(files)) == 1

    def test_provider_list_upload_download_delete(
        self, serverless_client: ServerlessClient
    ):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test-local-provider-function:latest",
        )
        serverless_client.upload(function)

        function = serverless_client.function("mockprovider/provider-function")

        print("::: Provider file_upload :::")
        print(serverless_client.provider_file_upload(filename_path, function))

        files = serverless_client.provider_files(function)
        print("::: Provider files :::")
        print(files)

        file_count = len(files)
        print("::: Provider file_count :::")
        print(file_count)

        assert file_count == 1

        print("::: Provider file_download :::")
        assert serverless_client.provider_file_download(filename, function) is not None

        files = serverless_client.provider_files(function)
        print("::: Provider files after download :::")
        print(files)

        assert file_count == len(files)

        print("::: Provider file_delete :::")
        print(serverless_client.provider_file_delete(filename, function))

        print("::: Provider files after delete:::")
        files = serverless_client.provider_files(function)
        print(files)

        assert (file_count - len(files)) == 1
