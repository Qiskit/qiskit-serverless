# This code is a Qiskit project.
#
# (C) Copyright IBM 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for GatewayFilesClient."""

import os
import tempfile
from unittest.mock import MagicMock, Mock, patch, mock_open

import pytest

from qiskit_serverless.core.files import GatewayFilesClient
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException


@pytest.fixture
def files_client():
    """Create a GatewayFilesClient for testing."""
    return GatewayFilesClient(
        host="https://test-host.com",
        token="test-token",
        version="v1",
        instance="test-instance",
        channel="ibm_quantum_platform",
    )


@pytest.fixture
def test_function():
    """Create a test QiskitFunction."""
    return QiskitFunction(
        title="test-function",
        provider="test-provider",
    )


@pytest.fixture
def test_function_no_provider():
    """Create a test QiskitFunction without provider."""
    return QiskitFunction(
        title="test-function",
    )


class TestGatewayFilesClientInit:
    """Tests for GatewayFilesClient initialization."""

    def test_init_with_all_parameters(self):
        """Client initializes correctly with all parameters."""
        client = GatewayFilesClient(
            host="https://test-host.com",
            token="test-token",
            version="v1",
            instance="test-instance",
            channel="test-channel",
        )

        assert client.host == "https://test-host.com"
        assert client.version == "v1"
        assert client._token == "test-token"
        assert client._instance == "test-instance"
        assert client._channel == "test-channel"
        assert client._files_url == "https://test-host.com/api/v1/files"

    def test_init_without_optional_parameters(self):
        """Client initializes correctly without optional parameters."""
        client = GatewayFilesClient(
            host="https://test-host.com",
            token="test-token",
            version="v1",
        )

        assert client.host == "https://test-host.com"
        assert client._token == "test-token"
        assert client._instance is None
        assert client._channel is None


class TestDownload:
    """Tests for download() method."""

    @patch("qiskit_serverless.core.files.requests.get")
    @patch("qiskit_serverless.core.files.tqdm")
    def test_download_success(self, mock_tqdm, mock_get, files_client, test_function):
        """download() successfully downloads a file."""
        # Mock response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-length": "1024"}
        mock_response.iter_content = MagicMock(return_value=[b"chunk1", b"chunk2"])
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        # Mock progress bar
        mock_progress = MagicMock()
        mock_tqdm.return_value = mock_progress

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("builtins.open", mock_open()) as mock_file:
                result = files_client.download(
                    file="test.txt",
                    download_location=temp_dir,
                    function=test_function,
                    target_name="downloaded.txt",
                )

                assert result == "downloaded.txt"
                mock_get.assert_called_once()
                call_kwargs = mock_get.call_args[1]
                assert call_kwargs["params"]["file"] == "test.txt"
                assert call_kwargs["params"]["provider"] == "test-provider"
                assert call_kwargs["params"]["function"] == "test-function"
                assert call_kwargs["stream"] is True

    @patch("qiskit_serverless.core.files.requests.get")
    @patch("qiskit_serverless.core.files.tqdm")
    def test_download_without_target_name(self, mock_tqdm, mock_get, files_client, test_function):
        """download() generates a filename when target_name is not provided."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-length": "1024"}
        mock_response.iter_content = MagicMock(return_value=[b"chunk"])
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        mock_progress = MagicMock()
        mock_tqdm.return_value = mock_progress

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("builtins.open", mock_open()):
                result = files_client.download(
                    file="test.txt",
                    download_location=temp_dir,
                    function=test_function,
                )

                assert result is not None
                assert result.startswith("downloaded_")
                assert result.endswith("_test.txt")

    @patch("qiskit_serverless.core.files.requests.get")
    def test_download_raises_on_http_error(self, mock_get, files_client, test_function):
        """download() raises exception on HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP Error")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(Exception, match="HTTP Error"):
                files_client.download(
                    file="test.txt",
                    download_location=temp_dir,
                    function=test_function,
                )


class TestProviderDownload:
    """Tests for provider_download() method."""

    @patch("qiskit_serverless.core.files.requests.get")
    @patch("qiskit_serverless.core.files.tqdm")
    def test_provider_download_success(self, mock_tqdm, mock_get, files_client, test_function):
        """provider_download() successfully downloads a file."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-length": "1024"}
        mock_response.iter_content = MagicMock(return_value=[b"chunk"])
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_get.return_value = mock_response

        mock_progress = MagicMock()
        mock_tqdm.return_value = mock_progress

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("builtins.open", mock_open()):
                result = files_client.provider_download(
                    file="test.txt",
                    download_location=temp_dir,
                    function=test_function,
                    target_name="downloaded.txt",
                )

                assert result == "downloaded.txt"
                # Verify it uses the provider endpoint
                call_url = mock_get.call_args[0][0]
                assert "provider/download" in call_url

    def test_provider_download_raises_without_provider(self, files_client, test_function_no_provider):
        """provider_download() raises exception when function has no provider."""
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(QiskitServerlessException, match="doesn't have a provider"):
                files_client.provider_download(
                    file="test.txt",
                    download_location=temp_dir,
                    function=test_function_no_provider,
                )


class TestUpload:
    """Tests for upload() method."""

    @patch("qiskit_serverless.core.files.requests.post")
    def test_upload_success(self, mock_post, files_client, test_function):
        """upload() successfully uploads a file."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = "Upload successful"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_response

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            result = files_client.upload(file=temp_file_path, function=test_function)

            assert result == "Upload successful"
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["params"]["provider"] == "test-provider"
            assert call_kwargs["params"]["function"] == "test-function"
            assert call_kwargs["stream"] is True
        finally:
            os.unlink(temp_file_path)

    @patch("qiskit_serverless.core.files.requests.post")
    def test_upload_raises_on_failure(self, mock_post, files_client, test_function):
        """upload() raises exception when upload fails."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_response

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            with pytest.raises(QiskitServerlessException, match="Upload failed"):
                files_client.upload(file=temp_file_path, function=test_function)
        finally:
            os.unlink(temp_file_path)

    def test_upload_raises_when_file_not_found(self, files_client, test_function):
        """upload() raises exception when file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            files_client.upload(file="nonexistent.txt", function=test_function)


class TestProviderUpload:
    """Tests for provider_upload() method."""

    @patch("qiskit_serverless.core.files.requests.post")
    def test_provider_upload_success(self, mock_post, files_client, test_function):
        """provider_upload() successfully uploads a file."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.text = "Upload successful"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_response

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            result = files_client.provider_upload(file=temp_file_path, function=test_function)

            assert result == "Upload successful"
            # Verify it uses the provider endpoint
            call_url = mock_post.call_args[0][0]
            assert "provider/upload" in call_url
        finally:
            os.unlink(temp_file_path)

    def test_provider_upload_raises_without_provider(self, files_client, test_function_no_provider):
        """provider_upload() raises exception when function has no provider."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            with pytest.raises(QiskitServerlessException, match="doesn't have a provider"):
                files_client.provider_upload(file=temp_file_path, function=test_function_no_provider)
        finally:
            os.unlink(temp_file_path)

    @patch("qiskit_serverless.core.files.requests.post")
    def test_provider_upload_raises_on_failure(self, mock_post, files_client, test_function):
        """provider_upload() raises exception when upload fails."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_post.return_value = mock_response

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as temp_file:
            temp_file.write("test content")
            temp_file_path = temp_file.name

        try:
            with pytest.raises(QiskitServerlessException, match="Upload failed"):
                files_client.provider_upload(file=temp_file_path, function=test_function)
        finally:
            os.unlink(temp_file_path)


class TestList:
    """Tests for list() method."""

    @patch("qiskit_serverless.core.files.requests.get")
    def test_list_returns_file_list(self, mock_get, files_client, test_function):
        """list() returns a list of files."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"results": ["file1.txt", "file2.txt", "file3.txt"]}'
        mock_response.json.return_value = {"results": ["file1.txt", "file2.txt", "file3.txt"]}
        mock_get.return_value = mock_response

        result = files_client.list(function=test_function)

        assert result == ["file1.txt", "file2.txt", "file3.txt"]
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["function"] == "test-function"
        assert call_kwargs["params"]["provider"] == "test-provider"

    @patch("qiskit_serverless.core.files.requests.get")
    def test_list_returns_empty_list_when_no_files(self, mock_get, files_client, test_function):
        """list() returns an empty list when no files exist."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"results": []}'
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        result = files_client.list(function=test_function)

        assert result == []

    @patch("qiskit_serverless.core.files.requests.get")
    def test_list_returns_empty_list_when_results_missing(self, mock_get, files_client, test_function):
        """list() returns an empty list when 'results' key is missing."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response

        result = files_client.list(function=test_function)

        assert result == []


class TestProviderList:
    """Tests for provider_list() method."""

    @patch("qiskit_serverless.core.files.requests.get")
    def test_provider_list_returns_file_list(self, mock_get, files_client, test_function):
        """provider_list() returns a list of files."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"results": ["provider_file1.txt", "provider_file2.txt"]}'
        mock_response.json.return_value = {"results": ["provider_file1.txt", "provider_file2.txt"]}
        mock_get.return_value = mock_response

        result = files_client.provider_list(function=test_function)

        assert result == ["provider_file1.txt", "provider_file2.txt"]
        # Verify it uses the provider endpoint
        call_url = mock_get.call_args[0][0]
        assert "provider" in call_url

    def test_provider_list_raises_without_provider(self, files_client, test_function_no_provider):
        """provider_list() raises exception when function has no provider."""
        with pytest.raises(QiskitServerlessException, match="doesn't have a provider"):
            files_client.provider_list(function=test_function_no_provider)

    @patch("qiskit_serverless.core.files.requests.get")
    def test_provider_list_returns_empty_list_when_no_files(self, mock_get, files_client, test_function):
        """provider_list() returns an empty list when no files exist."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"results": []}'
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response

        result = files_client.provider_list(function=test_function)

        assert result == []


class TestDelete:
    """Tests for delete() method."""

    @patch("qiskit_serverless.core.files.requests.delete")
    def test_delete_success(self, mock_delete, files_client, test_function):
        """delete() successfully deletes a file."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"message": "File deleted successfully"}'
        mock_response.json.return_value = {"message": "File deleted successfully"}
        mock_delete.return_value = mock_response

        result = files_client.delete(file="test.txt", function=test_function)

        assert result == "File deleted successfully"
        mock_delete.assert_called_once()
        call_kwargs = mock_delete.call_args[1]
        assert call_kwargs["params"]["file"] == "test.txt"
        assert call_kwargs["params"]["function"] == "test-function"
        assert call_kwargs["params"]["provider"] == "test-provider"

    @patch("qiskit_serverless.core.files.requests.delete")
    def test_delete_returns_empty_string_when_message_missing(self, mock_delete, files_client, test_function):
        """delete() returns empty string when 'message' key is missing."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "{}"
        mock_response.json.return_value = {}
        mock_delete.return_value = mock_response

        result = files_client.delete(file="test.txt", function=test_function)

        assert result == ""

    @patch("qiskit_serverless.core.files.requests.delete")
    def test_delete_includes_format_header(self, mock_delete, files_client, test_function):
        """delete() includes 'format': 'json' in headers."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"message": "Deleted"}'
        mock_response.json.return_value = {"message": "Deleted"}
        mock_delete.return_value = mock_response

        files_client.delete(file="test.txt", function=test_function)

        call_kwargs = mock_delete.call_args[1]
        assert call_kwargs["headers"]["format"] == "json"


class TestProviderDelete:
    """Tests for provider_delete() method."""

    @patch("qiskit_serverless.core.files.requests.delete")
    def test_provider_delete_success(self, mock_delete, files_client, test_function):
        """provider_delete() successfully deletes a file."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"message": "File deleted successfully"}'
        mock_response.json.return_value = {"message": "File deleted successfully"}
        mock_delete.return_value = mock_response

        result = files_client.provider_delete(file="test.txt", function=test_function)

        assert result == "File deleted successfully"
        # Verify it uses the provider endpoint
        call_url = mock_delete.call_args[0][0]
        assert "provider/delete" in call_url

    def test_provider_delete_raises_without_provider(self, files_client, test_function_no_provider):
        """provider_delete() raises exception when function has no provider."""
        with pytest.raises(QiskitServerlessException, match="doesn't have a provider"):
            files_client.provider_delete(file="test.txt", function=test_function_no_provider)

    @patch("qiskit_serverless.core.files.requests.delete")
    def test_provider_delete_includes_format_header(self, mock_delete, files_client, test_function):
        """provider_delete() includes 'format': 'json' in headers."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"message": "Deleted"}'
        mock_response.json.return_value = {"message": "Deleted"}
        mock_delete.return_value = mock_response

        files_client.provider_delete(file="test.txt", function=test_function)

        call_kwargs = mock_delete.call_args[1]
        assert call_kwargs["headers"]["format"] == "json"
