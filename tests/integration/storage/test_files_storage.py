# pylint: disable=import-error, invalid-name, duplicate-code
"""Tests jobs."""

import os

from pytest import raises

from qiskit_serverless import QiskitServerlessException, ServerlessClient, QiskitFunction

resources_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../source_files")

filename = "test.txt"
filename_path = os.path.join(resources_path, filename)
filename_not_valid = "test-img.png"
filename_not_valid_path = os.path.join(resources_path, filename_not_valid)


class TestFilesStorage:
    """Test class for integration tests producing and consuming files"""

    def test_list_upload_download_delete(self, serverless_client: ServerlessClient, tmp_path):
        """Integration test for upload files."""

        function = QiskitFunction(
            title="hello-world",
            entrypoint="hello_world.py",
            working_dir=resources_path,
        )
        function = serverless_client.upload(function)

        print(serverless_client.file_upload(filename_path, function))
        files = serverless_client.files(function)
        print(files)

        assert filename in files

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        assert serverless_client.file_download(filename, function, download_location=str(download_dir)) is not None

        print(serverless_client.file_delete(filename, function))
        files = serverless_client.files(function)
        print(files)

        assert filename not in files

    def test_list_upload_download_delete_with_provider_function(self, serverless_client: ServerlessClient, tmp_path):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test/local-provider-function:latest",
        )
        serverless_client.upload(function)

        function = serverless_client.function("mockprovider/provider-function")

        print(serverless_client.file_upload(filename_path, function))
        files = serverless_client.files(function)
        print(files)

        assert filename in files

        download_dir = tmp_path / "downloads"
        download_dir.mkdir()
        assert serverless_client.file_download(filename, function, download_location=str(download_dir)) is not None

        print(serverless_client.file_delete(filename, function))
        files = serverless_client.files(function)
        print(files)

        assert filename not in files

    def test_provider_list_upload_download_delete(self, serverless_client: ServerlessClient, tmp_path):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test/local-provider-function:latest",
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
            serverless_client.provider_file_download(filename, function, download_location=str(download_dir))
            is not None
        )

        print(serverless_client.provider_file_delete(filename, function))
        files = serverless_client.provider_files(function)
        print(files)

        assert filename not in files

    def test_provider_upload_failed(self, serverless_client: ServerlessClient):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="provider-function",
            provider="mockprovider",
            image="test/local-provider-function:latest",
        )
        function = serverless_client.upload(function)

        with raises(QiskitServerlessException) as exc_info:
            serverless_client.provider_file_upload(filename_not_valid_path, function)

        expected_message = (
            "Upload failed: \n\n| Message: Http bad request.\n| Code: 400\n| "
            "Details:\n|   - message: Uploaded file is not a valid type."
        )
        assert expected_message in str(exc_info.value)

    def test_upload_failed(self, serverless_client: ServerlessClient):
        """Integration test for upload files."""
        function = QiskitFunction(
            title="hello-world",
            entrypoint="hello_world.py",
            working_dir=resources_path,
        )
        function = serverless_client.upload(function)

        with raises(QiskitServerlessException) as exc_info:
            serverless_client.file_upload(filename_not_valid_path, function)

        expected_message = (
            "Upload failed: \n\n| Message: Http bad request.\n| Code: 400\n| "
            "Details:\n|   - message: Uploaded file is not a valid type."
        )
        assert expected_message in str(exc_info.value)
