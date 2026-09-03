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

import json
import os
import tempfile
from unittest.mock import MagicMock, patch, Mock

import pytest

from qiskit_serverless.core.clients.serverless_client import (
    ServerlessClient,
    _sizes_payload,
    _upload_with_docker_image,
    _upload_with_artifact,
)
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
        assert data["runner"] == "ray"
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
        assert data["runner"] == "ray"
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

    def test_default_runner_is_ray(self):
        """QiskitFunction.runner defaults to 'ray' when not specified."""
        program = QiskitFunction(title="my-function", image="img:latest")
        assert program.runner == "ray"

    def test_runner_can_be_overridden(self):
        """QiskitFunction.runner accepts a custom value."""
        program = QiskitFunction(title="my-function", image="img:latest", runner="fleets")
        assert program.runner == "fleets"


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
