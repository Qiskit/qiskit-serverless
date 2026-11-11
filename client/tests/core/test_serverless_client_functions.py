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

"""Tests for ServerlessClient function-related operations."""

import hashlib
import json
import os
import tempfile
import warnings
from unittest.mock import MagicMock, patch, Mock

import pytest

from qiskit_serverless.core.clients.serverless_client import (
    ServerlessClient,
    _sizes_payload,
    _upload_with_docker_image,
    _upload_with_artifact,
)
from qiskit_serverless.core.compute_profile import ComputeProfile
from qiskit_serverless.core.function import QiskitFunction, RunnableQiskitFunction
from qiskit_serverless.exception import QiskitServerlessException


@pytest.fixture
def mock_client():
    """Create a mock ServerlessClient for testing."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.text = '{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}

    with patch("qiskit_serverless.core.clients.serverless_client.requests.get", return_value=mock_response):
        client = ServerlessClient(
            host="https://test-host.com",
            token="test-token",
            instance="test-instance",
            channel="ibm_quantum_platform",
            version="v1",
        )
    return client


class TestUploadMethod:
    """Tests for ServerlessClient.upload() method."""

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_with_docker_image_calls_correct_helper(self, mock_trace, mock_upload_docker, mock_client):
        """upload() calls _upload_with_docker_image when program has image."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_function = MagicMock(spec=RunnableQiskitFunction)
        mock_upload_docker.return_value = mock_function

        program = QiskitFunction(
            title="test-function",
            image="test-image:latest",
        )

        result = mock_client.upload(program)

        mock_upload_docker.assert_called_once()
        call_kwargs = mock_upload_docker.call_args[1]
        assert call_kwargs["program"] == program
        assert call_kwargs["url"].endswith("/api/v1/programs/upload/")
        assert call_kwargs["token"] == "test-token"
        assert call_kwargs["client"] == mock_client
        assert result == mock_function

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_artifact")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_with_artifact_calls_correct_helper(self, mock_trace, mock_upload_artifact, mock_client):
        """upload() calls _upload_with_artifact when program has entrypoint."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_function = MagicMock(spec=RunnableQiskitFunction)
        mock_upload_artifact.return_value = mock_function

        program = QiskitFunction(
            title="test-function",
            entrypoint="main.py",
            working_dir="./",
        )

        result = mock_client.upload(program)

        mock_upload_artifact.assert_called_once()
        call_kwargs = mock_upload_artifact.call_args[1]
        assert call_kwargs["program"] == program
        assert call_kwargs["url"].endswith("/api/v1/programs/upload/")
        assert call_kwargs["token"] == "test-token"
        assert call_kwargs["client"] == mock_client
        assert result == mock_function

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_warns_when_dependencies_set(self, mock_trace, mock_upload_docker, mock_client):
        """upload() emits a DeprecationWarning when the deprecated `dependencies=` is used."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_upload_docker.return_value = MagicMock(spec=RunnableQiskitFunction)

        program = QiskitFunction(
            title="test-function",
            image="test-image:latest",
            dependencies=["numpy", "scipy"],
        )

        with pytest.warns(DeprecationWarning, match="no longer installs anything"):
            mock_client.upload(program)

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_does_not_warn_without_dependencies(self, mock_trace, mock_upload_docker, mock_client):
        """upload() does not emit a DeprecationWarning when `dependencies=` is unset."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_upload_docker.return_value = MagicMock(spec=RunnableQiskitFunction)

        program = QiskitFunction(title="test-function", image="test-image:latest")

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            mock_client.upload(program)

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_warns_when_runner_is_ray(self, mock_trace, mock_upload_docker, mock_client):
        """upload() emits a DeprecationWarning when the function's runner is 'ray'."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_upload_docker.return_value = MagicMock(spec=RunnableQiskitFunction)

        program = QiskitFunction(title="test-function", image="test-image:latest", runner="ray")

        with pytest.warns(DeprecationWarning, match="Ray runner is deprecated"):
            mock_client.upload(program)

    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_does_not_warn_for_fleets_runner(self, mock_trace, mock_upload_docker, mock_client):
        """upload() does not emit the Ray DeprecationWarning for a Fleets function."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span
        mock_upload_docker.return_value = MagicMock(spec=RunnableQiskitFunction)

        program = QiskitFunction(title="test-function", image="test-image:latest", runner="fleets")

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            mock_client.upload(program)

    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_raises_when_neither_image_nor_entrypoint(self, mock_trace, mock_client):
        """upload() raises QiskitServerlessException when program has neither image nor entrypoint."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        program = QiskitFunction(title="test-function")

        with pytest.raises(QiskitServerlessException, match="must either have `entrypoint` or `image` specified"):
            mock_client.upload(program)

    @pytest.mark.parametrize(
        "program_kwargs,expected_upload_type",
        [
            ({"image": "test:latest"}, "docker"),
            ({"entrypoint": "main.py", "working_dir": "./"}, "artifact"),
        ],
    )
    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_artifact")
    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_routes_to_correct_helper(
        self, mock_trace, mock_docker, mock_artifact, mock_client, program_kwargs, expected_upload_type
    ):
        """upload() routes to the correct helper based on program configuration."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_function = MagicMock(spec=RunnableQiskitFunction)
        mock_docker.return_value = mock_function
        mock_artifact.return_value = mock_function

        program = QiskitFunction(title="test-function", **program_kwargs)
        mock_client.upload(program)

        if expected_upload_type == "docker":
            mock_docker.assert_called_once()
            mock_artifact.assert_not_called()
        else:
            mock_artifact.assert_called_once()
            mock_docker.assert_not_called()

    @pytest.mark.parametrize(
        "optional_fields",
        [
            {},
            {"provider": "test-provider"},
            {"dependencies": ["numpy", "scipy"]},
            {"env_vars": {"KEY": "VALUE"}},
            {"description": "Test description"},
            {"version": "1.0.0"},
            {
                "provider": "test-provider",
                "dependencies": ["qiskit"],
                "env_vars": {"ENV": "test"},
                "description": "Full test",
                "version": "2.0.0",
            },
        ],
    )
    @patch("qiskit_serverless.core.clients.serverless_client._upload_with_docker_image")
    @patch("qiskit_serverless.core.clients.serverless_client.trace")
    def test_upload_handles_various_optional_fields(self, mock_trace, mock_upload, mock_client, optional_fields):
        """upload() correctly handles various combinations of optional fields."""
        mock_span = MagicMock()
        mock_trace.get_tracer.return_value.start_as_current_span.return_value.__enter__.return_value = mock_span

        mock_function = MagicMock(spec=RunnableQiskitFunction)
        mock_upload.return_value = mock_function

        program = QiskitFunction(title="test-function", image="test:latest", **optional_fields)
        result = mock_client.upload(program)

        mock_upload.assert_called_once()
        assert result == mock_function


class TestFunctionsMethod:
    """Tests for ServerlessClient.functions() method."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_functions_returns_list_of_runnable_functions(self, mock_get, mock_client):
        """functions() returns a list of RunnableQiskitFunction objects."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '[{"title": "function1", "provider": "provider1", "id": "id1"}, {"title": "function2", "provider": "provider2", "id": "id2"}]'
        mock_response.json.return_value = [
            {"title": "function1", "provider": "provider1", "id": "id1"},
            {"title": "function2", "provider": "provider2", "id": "id2"},
        ]
        mock_get.return_value = mock_response

        functions = mock_client.functions()

        assert len(functions) == 2
        assert all(isinstance(f, RunnableQiskitFunction) for f in functions)
        assert functions[0].title == "function1"
        assert functions[0].provider == "provider1"
        assert functions[1].title == "function2"
        assert functions[1].provider == "provider2"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_functions_passes_query_parameters(self, mock_get, mock_client):
        """functions() passes query parameters to the API request."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        mock_client.functions(limit=5, offset=10, provider="test-provider")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"] == {"limit": 5, "offset": 10, "provider": "test-provider"}

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_functions_passes_provider_filter(self, mock_get, mock_client):
        """functions(provider=...) forwards the provider as a query parameter."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        mock_client.functions(provider="q-ctrl")

        mock_get.assert_called_once()
        assert mock_get.call_args[1]["params"] == {"provider": "q-ctrl"}

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_functions_returns_empty_list_when_no_functions(self, mock_get, mock_client):
        """functions() returns an empty list when no functions are available."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        functions = mock_client.functions()

        assert functions == []

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_functions_injects_client_into_response_data(self, mock_get, mock_client):
        """functions() injects the client instance into each function's data."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '[{"title": "function1", "provider": "provider1", "id": "id1"}]'
        mock_response.json.return_value = [
            {"title": "function1", "provider": "provider1", "id": "id1"},
        ]
        mock_get.return_value = mock_response

        functions = mock_client.functions()

        assert functions[0]._run_service == mock_client


class TestFunctionMethod:
    """Tests for ServerlessClient.function() method."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_returns_single_runnable_function(self, mock_get, mock_client):
        """function() returns a single RunnableQiskitFunction object."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"title": "test-function", "provider": "test-provider", "id": "test-id"}'
        mock_response.json.return_value = {
            "title": "test-function",
            "provider": "test-provider",
            "id": "test-id",
        }
        mock_get.return_value = mock_response

        function = mock_client.function(title="test-function", provider="test-provider")

        assert isinstance(function, RunnableQiskitFunction)
        assert function.title == "test-function"
        assert function.provider == "test-provider"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_decodes_arguments_schema_into_dict(self, mock_get, mock_client):
        """The gateway sends arguments_schema as text, so it must come back as a dict."""
        payload = {
            "title": "test-function",
            "provider": "test-provider",
            "id": "test-id",
            "arguments_schema": json.dumps({"type": "object", "required": ["shots"]}),
        }
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_get.return_value = mock_response

        function = mock_client.function(title="test-function", provider="test-provider")

        assert function.arguments_schema == {"type": "object", "required": ["shots"]}

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_uses_format_provider_name_and_title(self, mock_get, mock_client):
        """function() uses format_provider_name_and_title to parse title."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"title": "my-function", "provider": "my-provider", "id": "test-id"}'
        mock_response.json.return_value = {
            "title": "my-function",
            "provider": "my-provider",
            "id": "test-id",
        }
        mock_get.return_value = mock_response

        # Test with provider/title format
        function = mock_client.function(title="my-provider/my-function")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert "my-function" in mock_get.call_args[0][0]
        assert call_kwargs["params"]["provider"] == "my-provider"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_with_explicit_provider(self, mock_get, mock_client):
        """function() uses explicit provider parameter when provided."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"title": "test-function", "provider": "explicit-provider", "id": "test-id"}'
        mock_response.json.return_value = {
            "title": "test-function",
            "provider": "explicit-provider",
            "id": "test-id",
        }
        mock_get.return_value = mock_response

        function = mock_client.function(title="test-function", provider="explicit-provider")

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["provider"] == "explicit-provider"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_injects_client_into_response(self, mock_get, mock_client):
        """function() injects the client instance into the function's data."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"title": "test-function", "provider": "test-provider", "id": "test-id"}'
        mock_response.json.return_value = {
            "title": "test-function",
            "provider": "test-provider",
            "id": "test-id",
        }
        mock_get.return_value = mock_response

        function = mock_client.function(title="test-function")

        assert function._run_service == mock_client


class TestDependenciesVersionsMethod:
    """Tests for ServerlessClient.dependencies_versions() method."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_dependencies_versions_returns_list(self, mock_get, mock_client):
        """dependencies_versions() returns a list of available dependencies."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '[{"name": "qiskit", "version": "1.0.0"}, {"name": "numpy", "version": "1.24.0"}]'
        mock_response.json.return_value = [
            {"name": "qiskit", "version": "1.0.0"},
            {"name": "numpy", "version": "1.24.0"},
        ]
        mock_get.return_value = mock_response

        dependencies = mock_client.dependencies_versions()

        assert len(dependencies) == 2
        assert dependencies[0]["name"] == "qiskit"
        assert dependencies[1]["name"] == "numpy"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_dependencies_versions_calls_correct_endpoint(self, mock_get, mock_client):
        """dependencies_versions() calls the correct API endpoint."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        mock_client.dependencies_versions()

        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0] if mock_get.call_args[0] else mock_get.call_args[1]["url"]
        assert "dependencies-versions" in call_url

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_dependencies_versions_returns_empty_list_when_none_available(self, mock_get, mock_client):
        """dependencies_versions() returns an empty list when no dependencies are available."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        dependencies = mock_client.dependencies_versions()

        assert dependencies == []


def _write_wheel(tmp_path, name, size):
    """Write a wheel file of ``size`` bytes of deterministic content; return its path."""
    path = tmp_path / name
    path.write_bytes(bytes((i % 251 for i in range(size))))
    return str(path)


class TestAddWheelsMethod:
    """Tests for ServerlessClient.add_wheels()."""

    def test_add_wheels_uploads_each_matching_wheel(self, mock_client, tmp_path):
        """add_wheels expands patterns and uploads each small wheel whole via file_upload."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        a = _write_wheel(tmp_path, "a-1.0-py3-none-any.whl", 100)
        b = _write_wheel(tmp_path, "b-2.0-py3-none-any.whl", 100)
        with patch.object(mock_client, "file_upload") as mock_upload, patch.object(
            mock_client, "files", return_value=[]
        ), patch("qiskit_serverless.core.clients.serverless_client.glob.glob") as mock_glob:
            mock_glob.side_effect = lambda p: {"dist/a-*.whl": [a], "dist/b-*.whl": [b]}[p]

            uploaded = mock_client.add_wheels(function, ["dist/a-*.whl", "dist/b-*.whl"])

        assert uploaded == ["a-1.0-py3-none-any.whl", "b-2.0-py3-none-any.whl"]
        assert mock_upload.call_count == 2  # no manifest written (nothing chunked)
        for call in mock_upload.call_args_list:
            assert call.kwargs.get("sub_path") == "wheels"

    def test_add_wheels_raises_when_pattern_matches_nothing(self, mock_client):
        """add_wheels raises if a pattern matches no files."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        with patch("qiskit_serverless.core.clients.serverless_client.glob.glob", return_value=[]):
            with pytest.raises(QiskitServerlessException, match="No files match"):
                mock_client.add_wheels(function, ["dist/missing-*.whl"])

    def test_add_wheels_rejects_non_wheel_files(self, mock_client):
        """add_wheels rejects a match that is not a .whl file."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        with patch(
            "qiskit_serverless.core.clients.serverless_client.glob.glob",
            return_value=["dist/notawheel.tar.gz"],
        ):
            with pytest.raises(QiskitServerlessException, match="only accepts .whl"):
                mock_client.add_wheels(function, ["dist/*"])

    def test_wheel_at_threshold_uploads_whole(self, mock_client, tmp_path, monkeypatch):
        """A wheel exactly at the threshold uploads whole (no chunking, no manifest)."""
        monkeypatch.setattr("qiskit_serverless.core.clients.serverless_client.WHEEL_CHUNK_THRESHOLD_MB", 1)
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        path = _write_wheel(tmp_path, "edge-1.0-py3-none-any.whl", 1024 * 1024)  # exactly 1 MB
        with patch.object(mock_client, "file_upload") as mock_upload, patch.object(
            mock_client, "files", return_value=[]
        ), patch("qiskit_serverless.core.clients.serverless_client.glob.glob", return_value=[path]):
            uploaded = mock_client.add_wheels(function, ["dist/edge-*.whl"])

        assert uploaded == ["edge-1.0-py3-none-any.whl"]
        assert mock_upload.call_count == 1  # whole, no parts, no manifest
        assert mock_upload.call_args_list[0].args[0] == path

    def test_large_wheel_is_split_into_parts_with_manifest(self, mock_client, tmp_path, monkeypatch):
        """A wheel over the threshold uploads as ordered parts plus a manifest."""
        monkeypatch.setattr("qiskit_serverless.core.clients.serverless_client.WHEEL_CHUNK_THRESHOLD_MB", 1)
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        data_size = 1024 * 1024 * 2 + 500  # 3 parts at 1 MB
        path = _write_wheel(tmp_path, "big-1.0-py3-none-any.whl", data_size)
        original = (tmp_path / "big-1.0-py3-none-any.whl").read_bytes()

        uploads = []  # (uploaded_basename, bytes)

        def _capture_upload(src, _function, sub_path=None):  # noqa: ARG001
            with open(src, "rb") as handle:
                uploads.append((os.path.basename(src), handle.read()))

        with patch.object(mock_client, "file_upload", side_effect=_capture_upload), patch.object(
            mock_client, "files", return_value=[]
        ), patch("qiskit_serverless.core.clients.serverless_client.glob.glob", return_value=[path]):
            uploaded = mock_client.add_wheels(function, ["dist/big-*.whl"])

        assert uploaded == ["big-1.0-py3-none-any.whl"]  # logical name returned
        names = [n for n, _ in uploads]
        part_names = [
            "big-1.0-py3-none-any.whl.part-0001-of-0003",
            "big-1.0-py3-none-any.whl.part-0002-of-0003",
            "big-1.0-py3-none-any.whl.part-0003-of-0003",
        ]
        assert part_names == [n for n in names if ".part-" in n]
        assert ".wheel-chunks-manifest.json" in names

        # Parts concatenate back to the original, and the manifest sha256 matches.
        joined = b"".join(b for n, b in uploads for _ in [0] if n in part_names)
        assert joined == original
        manifest_bytes = next(b for n, b in uploads if n == ".wheel-chunks-manifest.json")
        manifest = json.loads(manifest_bytes)
        entry = manifest["chunked_wheels"][0]
        assert entry["wheel"] == "big-1.0-py3-none-any.whl"
        assert entry["sha256"] == hashlib.sha256(original).hexdigest()
        assert entry["parts"] == part_names

    def test_reupload_cleans_stale_parts(self, mock_client, tmp_path, monkeypatch):
        """Re-adding a wheel deletes its previously-uploaded parts before uploading new ones."""
        monkeypatch.setattr("qiskit_serverless.core.clients.serverless_client.WHEEL_CHUNK_THRESHOLD_MB", 1)
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        path = _write_wheel(tmp_path, "big-1.0-py3-none-any.whl", 1024 * 1024 + 10)  # 2 parts now
        stale = [
            "big-1.0-py3-none-any.whl.part-0001-of-0004",
            "big-1.0-py3-none-any.whl.part-0002-of-0004",
            "big-1.0-py3-none-any.whl.part-0003-of-0004",
            "big-1.0-py3-none-any.whl.part-0004-of-0004",
        ]
        with patch.object(mock_client, "file_upload"), patch.object(
            mock_client, "file_delete"
        ) as mock_delete, patch.object(mock_client, "files", return_value=list(stale)), patch(
            "qiskit_serverless.core.clients.serverless_client.glob.glob", return_value=[path]
        ):
            mock_client.add_wheels(function, ["dist/big-*.whl"])

        deleted = [c.args[0] for c in mock_delete.call_args_list]
        assert set(stale).issubset(set(deleted))  # every stale part removed first

    def test_partial_failure_cleans_up_and_propagates(self, mock_client, tmp_path, monkeypatch):
        """If a part upload fails, already-uploaded parts are removed and the error propagates."""
        monkeypatch.setattr("qiskit_serverless.core.clients.serverless_client.WHEEL_CHUNK_THRESHOLD_MB", 1)
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        path = _write_wheel(tmp_path, "big-1.0-py3-none-any.whl", 1024 * 1024 * 2 + 1)  # 3 parts

        calls = {"n": 0}

        def _upload(src, _function, sub_path=None):  # noqa: ARG001
            if ".part-" in os.path.basename(src):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise QiskitServerlessException("boom")

        with patch.object(mock_client, "file_upload", side_effect=_upload), patch.object(
            mock_client, "file_delete"
        ) as mock_delete, patch.object(mock_client, "files", return_value=[]), patch(
            "qiskit_serverless.core.clients.serverless_client.glob.glob", return_value=[path]
        ):
            with pytest.raises(QiskitServerlessException, match="boom"):
                mock_client.add_wheels(function, ["dist/big-*.whl"])

        # the one part that uploaded before the failure is cleaned up
        assert any(".part-0001-of-0003" in c.args[0] for c in mock_delete.call_args_list)

    def test_list_wheels_lists_whole_wheels(self, mock_client):
        """list_wheels returns whole wheel names and hides nothing when no manifest exists."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        with patch.object(mock_client, "files", return_value=["mypkg-1.0-py3-none-any.whl"]) as mock_files:
            result = mock_client.list_wheels(function)

        assert mock_files.call_args_list[0].kwargs.get("sub_path") == "wheels"
        assert result == ["mypkg-1.0-py3-none-any.whl"]

    def test_list_wheels_hides_parts_and_manifest_shows_logical(self, mock_client):
        """list_wheels hides parts + manifest and surfaces chunked wheels by their logical name."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        listing = [
            "small-1.0-py3-none-any.whl",
            "big-1.0-py3-none-any.whl.part-0001-of-0002",
            "big-1.0-py3-none-any.whl.part-0002-of-0002",
            ".wheel-chunks-manifest.json",
        ]
        manifest = {"schema": 1, "chunked_wheels": [{"wheel": "big-1.0-py3-none-any.whl", "parts": []}]}
        with patch.object(mock_client, "files", return_value=listing), patch.object(
            mock_client, "_download_chunk_manifest", return_value=manifest
        ):
            result = mock_client.list_wheels(function)

        assert result == ["big-1.0-py3-none-any.whl", "small-1.0-py3-none-any.whl"]

    def test_remove_wheels_deletes_whole_from_the_wheels_subdir(self, mock_client):
        """remove_wheels deletes a whole wheel by name from the wheels sub-directory."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        with patch.object(mock_client, "file_delete") as mock_delete, patch.object(
            mock_client, "files", return_value=["a.whl", "b.whl"]
        ), patch.object(mock_client, "_download_chunk_manifest", return_value=None):
            mock_client.remove_wheels(function, ["a.whl", "b.whl"])

        deleted = [c.args[0] for c in mock_delete.call_args_list]
        assert deleted == ["a.whl", "b.whl"]
        for call in mock_delete.call_args_list:
            assert call.kwargs.get("sub_path") == "wheels"

    def test_remove_wheels_deletes_parts_and_prunes_manifest(self, mock_client):
        """Removing a chunked wheel deletes its parts and rewrites/deletes the manifest."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        parts = ["big-1.0-py3-none-any.whl.part-0001-of-0002", "big-1.0-py3-none-any.whl.part-0002-of-0002"]
        manifest = {"schema": 1, "chunked_wheels": [{"wheel": "big-1.0-py3-none-any.whl", "parts": parts}]}
        with patch.object(mock_client, "file_delete") as mock_delete, patch.object(
            mock_client, "files", return_value=list(parts + [".wheel-chunks-manifest.json"])
        ), patch.object(mock_client, "_download_chunk_manifest", return_value=manifest), patch.object(
            mock_client, "file_upload"
        ):
            mock_client.remove_wheels(function, ["big-1.0-py3-none-any.whl"])

        deleted = [c.args[0] for c in mock_delete.call_args_list]
        assert set(parts).issubset(set(deleted))
        # manifest now has no chunked wheels -> the manifest file itself is deleted
        assert ".wheel-chunks-manifest.json" in deleted

    def test_download_chunk_manifest_reads_from_the_wheels_subdir(self, mock_client):
        """_download_chunk_manifest downloads and parses the manifest from the wheels sub-dir.

        Exercises the real file_download call (argument order + sub_path), which the other tests
        stub out.
        """
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        payload = {"schema": 1, "chunked_wheels": [{"wheel": "big-1.0-py3-none-any.whl", "parts": ["p"]}]}

        def _fake_download(file, _function, target_name=None, download_location="./", sub_path=None):
            assert file == ".wheel-chunks-manifest.json"
            assert sub_path == "wheels"
            with open(os.path.join(download_location, target_name), "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

        with patch.object(mock_client, "files", return_value=[".wheel-chunks-manifest.json"]), patch.object(
            mock_client, "file_download", side_effect=_fake_download
        ):
            result = mock_client._download_chunk_manifest(function)

        assert result == payload

    def test_download_chunk_manifest_returns_none_when_absent(self, mock_client):
        """_download_chunk_manifest returns None (no download) when no manifest is present."""
        function = QiskitFunction(title="my-fn", provider="my-provider", entrypoint="main.py")
        with patch.object(mock_client, "files", return_value=["some.whl"]), patch.object(
            mock_client, "file_download"
        ) as mock_download:
            assert mock_client._download_chunk_manifest(function) is None
            mock_download.assert_not_called()


class TestDependencyReportMethod:
    """Tests for ServerlessClient.dependency_report()."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_dependency_report_classifies_each_requirement(self, mock_get, mock_client):
        """dependency_report marks requirements as baked / bring / clash."""
        baked = ["numpy==2.1.0", "qiskit-addon-aqc-tensor[quimb-jax]==0.3.1", "mergedeep==1.3.4"]
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = json.dumps(baked)
        mock_response.json.return_value = baked
        mock_get.return_value = mock_response

        report = mock_client.dependency_report(
            ["numpy>=2", "mypkg", "mergedeep==2.0.0", "qiskit_addon_aqc_tensor==0.3.1"]
        )

        by_req = {e.requirement: e.status for e in report}
        assert by_req["numpy>=2"] == "baked"
        assert by_req["mypkg"] == "bring"
        assert by_req["mergedeep==2.0.0"] == "clash"
        # name normalization: underscores/extras still match the baked entry
        assert by_req["qiskit_addon_aqc_tensor==0.3.1"] == "baked"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_dependency_report_prints_as_table(self, mock_get, mock_client):
        """The report renders as an aligned table with a header row."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        report = mock_client.dependency_report(["mypkg"])
        text = str(report)

        assert "requirement" in text and "status" in text and "note" in text
        assert "mypkg" in text


class TestUploadWithDockerImage:
    """Tests for _upload_with_docker_image helper function."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_payload_contains_all_fields(self, mock_post):
        """All fields from QiskitFunction are serialized correctly in the POST data."""
        mock_response = MagicMock()
        mock_response.ok = True
        payload = {"title": "my-function", "provider": "my-provider", "id": "abc-123"}
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_post.return_value = mock_response

        program = QiskitFunction(
            title="my-function",
            provider="my-provider",
            image="my-image:1.0",
            dependencies=["numpy", "scipy"],
            env_vars={"KEY": "VALUE"},
            description="A test function",
            version="1.2.3",
        )

        _upload_with_docker_image(
            program=program,
            url="http://gateway/api/v1/programs/",
            token="test-token",
            span=MagicMock(),
            client=MagicMock(),
            instance=None,
            channel=None,
        )

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        data = kwargs["data"]

        assert data["title"] == "my-function"
        assert data["provider"] == "my-provider"
        assert data["image"] == "my-image:1.0"
        assert data["runner"] == "fleets"
        assert data["arguments"] == json.dumps({})
        assert data["dependencies"] == json.dumps(["numpy", "scipy"])
        assert data["env_vars"] == json.dumps({"KEY": "VALUE"})
        assert data["description"] == "A test function"
        assert data["version"] == "1.2.3"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_optional_fields_default_correctly(self, mock_post):
        """Optional fields default to None / empty collections when not set."""
        mock_response = MagicMock()
        mock_response.ok = True
        payload = {"title": "my-function", "provider": None, "id": "abc-123"}
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_post.return_value = mock_response

        program = QiskitFunction(title="my-function", image="img:latest")

        _upload_with_docker_image(
            program=program,
            url="http://gateway/api/v1/programs/",
            token="test-token",
            span=MagicMock(),
            client=MagicMock(),
            instance=None,
            channel=None,
        )

        _, kwargs = mock_post.call_args
        data = kwargs["data"]

        assert data["provider"] is None
        assert data["dependencies"] == json.dumps([])
        assert data["env_vars"] == json.dumps({})
        assert data["description"] is None
        assert data["version"] is None


class TestUploadWithArtifact:
    """Tests for _upload_with_artifact helper function."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_payload_contains_all_fields(self, mock_post):
        """All fields from QiskitFunction are serialized correctly in the POST data."""
        mock_response = MagicMock()
        mock_response.ok = True
        payload = {"title": "my-function", "provider": "my-provider", "id": "abc-123"}
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as working_dir:
            entrypoint = "main.py"
            with open(os.path.join(working_dir, entrypoint), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            program = QiskitFunction(
                title="my-function",
                provider="my-provider",
                entrypoint=entrypoint,
                working_dir=working_dir,
                dependencies=["numpy", "scipy"],
                env_vars={"KEY": "VALUE"},
                description="A test function",
                version="2.0.0",
                arguments_schema={"type": "object", "properties": {"shots": {"type": "integer"}}},
            )

            _upload_with_artifact(
                program=program,
                url="http://gateway/api/v1/programs/",
                token="test-token",
                span=MagicMock(),
                client=MagicMock(),
                instance=None,
                channel=None,
            )

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        data = kwargs["data"]

        assert data["title"] == "my-function"
        assert data["provider"] == "my-provider"
        assert data["entrypoint"] == entrypoint
        assert data["runner"] == "fleets"
        assert data["arguments"] == json.dumps({})
        assert data["dependencies"] == json.dumps(["numpy", "scipy"])
        assert data["env_vars"] == json.dumps({"KEY": "VALUE"})
        assert data["description"] == "A test function"
        assert data["version"] == "2.0.0"
        assert json.loads(data["arguments_schema"]) == {
            "type": "object",
            "properties": {"shots": {"type": "integer"}},
        }

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_optional_fields_default_correctly(self, mock_post):
        """Optional fields default to None / empty collections when not set."""
        mock_response = MagicMock()
        mock_response.ok = True
        payload = {"title": "my-function", "provider": None, "id": "abc-123"}
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as working_dir:
            entrypoint = "main.py"
            with open(os.path.join(working_dir, entrypoint), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            program = QiskitFunction(
                title="my-function",
                entrypoint=entrypoint,
                working_dir=working_dir,
            )

            _upload_with_artifact(
                program=program,
                url="http://gateway/api/v1/programs/",
                token="test-token",
                span=MagicMock(),
                client=MagicMock(),
                instance=None,
                channel=None,
            )

        _, kwargs = mock_post.call_args
        data = kwargs["data"]

        assert data["provider"] is None
        assert data["dependencies"] == json.dumps([])
        assert data["env_vars"] == json.dumps({})
        assert data["description"] is None
        assert data["version"] is None

    def test_raises_when_entrypoint_does_not_exist(self):
        """QiskitServerlessException is raised when the entrypoint file is missing."""
        with tempfile.TemporaryDirectory() as working_dir:
            program = QiskitFunction(
                title="my-function",
                entrypoint="nonexistent.py",
                working_dir=working_dir,
            )
            with pytest.raises(QiskitServerlessException):
                _upload_with_artifact(
                    program=program,
                    url="http://gateway/api/v1/programs/",
                    token="test-token",
                    span=MagicMock(),
                    client=MagicMock(),
                    instance=None,
                    channel=None,
                )

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_tar_is_cleaned_up_after_upload(self, mock_post):
        """The temporary artifact.tar file is removed after a successful upload."""
        mock_response = MagicMock()
        mock_response.ok = True
        payload = {"title": "my-function", "provider": None, "id": "abc-123"}
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_post.return_value = mock_response

        with tempfile.TemporaryDirectory() as working_dir:
            entrypoint = "main.py"
            with open(os.path.join(working_dir, entrypoint), "w", encoding="utf-8") as f:
                f.write("print('hello')\n")

            program = QiskitFunction(
                title="my-function",
                entrypoint=entrypoint,
                working_dir=working_dir,
            )

            _upload_with_artifact(
                program=program,
                url="http://gateway/api/v1/programs/",
                token="test-token",
                span=MagicMock(),
                client=MagicMock(),
                instance=None,
                channel=None,
            )

            assert not os.path.exists(os.path.join(working_dir, "artifact.tar"))


class TestQiskitFunctionDefaults:
    """Tests for QiskitFunction default field values."""

    def test_default_runner_is_fleets(self):
        """QiskitFunction.runner defaults to 'fleets' when not specified."""
        program = QiskitFunction(title="my-function", image="img:latest")
        assert program.runner == "fleets"

    def test_runner_can_be_overridden(self):
        """QiskitFunction.runner accepts a custom value."""
        program = QiskitFunction(title="my-function", image="img:latest", runner="ray")
        assert program.runner == "ray"


class TestValidateArgumentsMethod:
    """Tests for ServerlessClient.validate_arguments()."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_validate_arguments_posts_to_endpoint_and_returns_result(self, mock_post, mock_client):
        """validate_arguments() POSTs title, provider and arguments, and returns the gateway response."""
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"valid": true}'
        mock_response.json.return_value = {"valid": True}
        mock_post.return_value = mock_response

        result = mock_client.validate_arguments(title="my-provider/my-function", arguments={"shots": 1024})

        mock_post.assert_called_once()
        url = mock_post.call_args[0][0] if mock_post.call_args[0] else mock_post.call_args[1]["url"]
        body = mock_post.call_args[1]["json"]
        assert "validate_arguments" in url
        assert body["title"] == "my-function"
        assert body["provider"] == "my-provider"
        assert json.loads(body["arguments"]) == {"shots": 1024}
        assert result == {"valid": True}

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_validate_arguments_raises_on_error_response(self, mock_post, mock_client):
        """validate_arguments() raises QiskitServerlessException when the gateway rejects the arguments."""
        mock_response = Mock()
        mock_response.ok = False
        mock_response.text = "{\"message\": \"'shots' is not of type 'integer'\"}"
        mock_response.json.return_value = {"message": "'shots' is not of type 'integer'"}
        mock_post.return_value = mock_response

        with pytest.raises(QiskitServerlessException):
            mock_client.validate_arguments(title="my-function", arguments={"shots": "wrong"})


class TestSizesMethod:
    """Tests for RunnableQiskitFunction.sizes() / get_default_size(), read from the representation."""

    def test_sizes_returns_catalog_from_representation(self, mock_client):
        """sizes() returns the catalog carried on the function, with no extra request."""
        function = RunnableQiskitFunction(
            mock_client, title="my-function", sizes_map={"s": "4x16", "m": "8x64"}, default_size="m"
        )

        assert function.sizes() == {"s": "4x16", "m": "8x64"}

    def test_get_default_size_returns_default_from_representation(self, mock_client):
        """get_default_size() returns the default label carried on the function."""
        function = RunnableQiskitFunction(mock_client, title="my-function", default_size="m")

        assert function.get_default_size() == "m"

    def test_sizes_empty_when_none_declared(self, mock_client):
        """A function that declares no sizes reports an empty catalog and no default."""
        function = RunnableQiskitFunction(mock_client, title="my-function", sizes_map={}, default_size=None)

        assert function.sizes() == {}
        assert function.get_default_size() is None

    def test_sizes_empty_when_representation_carried_nothing(self, mock_client):
        """sizes() normalizes a missing catalog (None) to an empty dict for the caller."""
        function = RunnableQiskitFunction(mock_client, title="my-function")

        assert function.sizes() == {}
        assert function.get_default_size() is None

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_function_reads_sizes_from_get_by_title_response(self, mock_get, mock_client):
        """A function fetched from the gateway carries sizes/default_size through from_json."""
        payload = {
            "title": "my-function",
            "provider": "my-provider",
            "id": "test-id",
            "sizes": {"s": "4x16", "m": "8x64"},
            "default_size": "m",
        }
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = json.dumps(payload)
        mock_response.json.return_value = payload
        mock_get.return_value = mock_response

        function = mock_client.function(title="my-function", provider="my-provider")

        assert function.sizes() == {"s": "4x16", "m": "8x64"}
        assert function.get_default_size() == "m"

    def test_from_json_remaps_sizes_key_onto_sizes_map(self):
        """The gateway's "sizes" key is remapped so it is not dropped by the field filter."""
        function = QiskitFunction.from_json({"title": "t", "sizes": {"s": "4x16"}, "default_size": "s"})

        assert function.sizes_map == {"s": "4x16"}
        assert function.default_size == "s"


class TestArgumentsSchemaDecoding:
    """Tests for how a stored arguments_schema is decoded when a function is read back."""

    def test_boolean_schema_is_kept_instead_of_looking_absent(self):
        """``false`` is the schema that rejects everything, so it must not read as "no schema"."""
        function = QiskitFunction.from_json({"title": "t", "arguments_schema": "false"})

        assert function.arguments_schema is False

    def test_empty_object_still_means_no_schema(self):
        """Regression lock: sending ``{}`` is how a schema is removed, and it reads back as None."""
        function = QiskitFunction.from_json({"title": "t", "arguments_schema": "{}"})

        assert function.arguments_schema is None

    def test_schema_that_is_not_an_object_or_boolean_is_rejected(self):
        """A JSON scalar is not a schema, so it must not leak through with the wrong type."""
        with pytest.raises(QiskitServerlessException):
            QiskitFunction.from_json({"title": "t", "arguments_schema": "123"})

    def test_schema_that_is_not_json_is_rejected(self):
        """A column value that is not JSON must raise the SDK exception, not a bare JSON error."""
        with pytest.raises(QiskitServerlessException):
            QiskitFunction.from_json({"title": "t", "arguments_schema": "not json at all"})


class TestSizesPayload:
    """Unit tests for _sizes_payload, the size-catalog part of an upload body."""

    def test_sends_sizes_map_under_gateway_key_as_json(self):
        """sizes_map goes out under the gateway's key ``sizes`` as a JSON object, not a dict."""
        program = QiskitFunction(
            title="t", entrypoint="e.py", runner="fleets", sizes_map={"s": "24x120", "m": "16x128"}
        )

        payload = _sizes_payload(program)

        assert payload == {"sizes": json.dumps({"s": "24x120", "m": "16x128"})}
        assert json.loads(payload["sizes"]) == {"s": "24x120", "m": "16x128"}

    def test_sends_default_size_as_plain_string(self):
        """default_size is a bare string, not JSON-encoded."""
        program = QiskitFunction(title="t", entrypoint="e.py", runner="fleets", default_size="m")

        assert _sizes_payload(program) == {"default_size": "m"}

    def test_sends_both_when_both_set(self):
        """Both fields go out together when both are set."""
        program = QiskitFunction(
            title="t", entrypoint="e.py", runner="fleets", sizes_map={"s": "24x120"}, default_size="s"
        )

        payload = _sizes_payload(program)

        assert set(payload) == {"sizes", "default_size"}
        assert payload["default_size"] == "s"

    def test_omits_unset_fields_so_stored_catalog_is_untouched(self):
        """Neither field is sent when unset: the gateway reads an absent field as "not sent"."""
        program = QiskitFunction(title="t", entrypoint="e.py", runner="fleets")

        assert _sizes_payload(program) == {}

    def test_empty_sizes_map_is_still_sent(self):
        """An empty dict is a deliberate value (declare no sizes), distinct from None (not sent)."""
        program = QiskitFunction(title="t", entrypoint="e.py", runner="fleets", sizes_map={})

        assert _sizes_payload(program) == {"sizes": json.dumps({})}

    def test_compute_profile_objects_serialize_to_their_id(self):
        """A ComputeProfile value is sent as its compute_profile_id, same wire shape as a string."""
        profile = ComputeProfile.from_json(
            {"compute_profile_id": "24x120x1l40s", "cpu": "24", "memory": "120", "gpu": "1l40s"}
        )
        program = QiskitFunction(title="t", entrypoint="e.py", runner="fleets", sizes_map={"s": "24x120", "m": profile})

        payload = _sizes_payload(program)

        # Identical to the all-strings form: the object is interchangeable with its id.
        assert payload == {"sizes": json.dumps({"s": "24x120", "m": "24x120x1l40s"})}


def _ok_response(response_json):
    """An ok requests response object carrying response_json (what requests.post returns)."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.status_code = 200
    mock_response.text = json.dumps(response_json)
    mock_response.json.return_value = response_json
    return mock_response


class TestUploadHelpersSendSizes:
    """The upload helpers must place the size fields into the POST body (regression lock)."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_docker_image_upload_includes_sizes(self, mock_post):
        """A docker-image upload carries sizes and default_size in its POST body."""
        mock_post.return_value = _ok_response({"title": "t"})

        program = QiskitFunction(
            title="t", image="registry/img:1", runner="fleets", sizes_map={"s": "24x120"}, default_size="s"
        )
        _upload_with_docker_image(
            program=program,
            url="http://gw/upload/",
            token="tok",
            span=MagicMock(),
            client=MagicMock(spec=ServerlessClient),
            instance=None,
            channel=None,
        )

        data = mock_post.call_args[1]["data"]
        assert data["sizes"] == json.dumps({"s": "24x120"})
        assert data["default_size"] == "s"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_docker_image_upload_omits_sizes_when_unset(self, mock_post):
        """With no catalog set, neither size field appears in the POST body."""
        mock_post.return_value = _ok_response({"title": "t"})

        program = QiskitFunction(title="t", image="registry/img:1", runner="fleets")
        _upload_with_docker_image(
            program=program,
            url="http://gw/upload/",
            token="tok",
            span=MagicMock(),
            client=MagicMock(spec=ServerlessClient),
            instance=None,
            channel=None,
        )

        data = mock_post.call_args[1]["data"]
        assert "sizes" not in data
        assert "default_size" not in data

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_artifact_upload_includes_sizes(self, mock_post):
        """An artifact upload carries sizes and default_size in its POST body."""
        mock_post.return_value = _ok_response({"title": "t"})

        with tempfile.TemporaryDirectory() as working_dir:
            with open(os.path.join(working_dir, "entrypoint.py"), "w", encoding="utf-8") as handle:
                handle.write("# entrypoint\n")
            program = QiskitFunction(
                title="t",
                entrypoint="entrypoint.py",
                working_dir=working_dir,
                runner="fleets",
                sizes_map={"s": "24x120", "m": "16x128"},
                default_size="m",
            )
            _upload_with_artifact(
                program=program,
                url="http://gw/upload/",
                token="tok",
                span=MagicMock(),
                client=MagicMock(spec=ServerlessClient),
                instance=None,
                channel=None,
            )

        data = mock_post.call_args[1]["data"]
        assert data["sizes"] == json.dumps({"s": "24x120", "m": "16x128"})
        assert data["default_size"] == "m"


class TestRunSurfacesGatewayWarning:
    """How ServerlessClient.run() surfaces the gateway's response ``warning`` field.

    The gateway returns the warning text (Ray deprecation, blocked resource, or both) for every
    client version. A recent client raises the category to ``DeprecationWarning`` when it can see
    locally that the function ran on the deprecated Ray runner.
    """

    _RAY_WARNING = (
        'This function runs on Ray, a deprecated platform. Please migrate to the Fleets runner (runner="fleets").'
    )

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_a_ray_function_warns_as_a_deprecation(self, mock_post, mock_client):
        mock_post.return_value = _ok_response({"id": "job-1", "warning": self._RAY_WARNING})
        program = QiskitFunction(title="my-func", image="img:latest", runner="ray")

        with pytest.warns(DeprecationWarning, match="deprecated platform"):
            mock_client.run(program)

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_a_fleets_function_with_no_warning_does_not_warn(self, mock_post, mock_client):
        mock_post.return_value = _ok_response({"id": "job-1"})
        program = QiskitFunction(title="my-func", image="img:latest", runner="fleets")

        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning would raise
            mock_client.run(program)

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_a_bare_title_falls_back_to_a_plain_warning(self, mock_post, mock_client):
        # Running by title gives the client no runner to inspect, so it cannot know this ran on
        # Ray; it still surfaces the gateway text, just not as a DeprecationWarning.
        mock_post.return_value = _ok_response({"id": "job-1", "warning": self._RAY_WARNING})

        with pytest.warns(UserWarning, match="deprecated platform") as caught:
            mock_client.run("my-func")
        assert not any(issubclass(w.category, DeprecationWarning) for w in caught)
