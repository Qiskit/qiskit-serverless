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

"""Tests for _upload_with_docker_image and _upload_with_artifact request payloads."""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from qiskit_serverless.core.clients.serverless_client import (
    _upload_with_docker_image,
    _upload_with_artifact,
)
from qiskit_serverless.core.function import QiskitFunction
from qiskit_serverless.exception import QiskitServerlessException

_UPLOAD_URL = "http://gateway/api/v1/programs/"
_TOKEN = "test-token"


def _make_mock_response(title="my-function", provider=None):
    """Return a mock requests.Response that looks like a successful upload."""
    mock_response = MagicMock()
    mock_response.ok = True
    payload = {"title": title, "provider": provider, "id": "abc-123"}
    mock_response.text = json.dumps(payload)
    mock_response.json.return_value = payload
    return mock_response


class TestUploadWithDockerImagePayload:
    """Tests that _upload_with_docker_image sends the correct POST payload."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_payload_contains_all_fields(self, mock_post):
        """All fields from QiskitFunction are serialized correctly in the POST data."""
        mock_post.return_value = _make_mock_response(title="my-function", provider="my-provider")

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
            url=_UPLOAD_URL,
            token=_TOKEN,
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
        assert data["arguments"] == json.dumps({})
        assert data["dependencies"] == json.dumps(["numpy", "scipy"])
        assert data["env_vars"] == json.dumps({"KEY": "VALUE"})
        assert data["description"] == "A test function"
        assert data["version"] == "1.2.3"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_optional_fields_default_correctly(self, mock_post):
        """Optional fields default to None / empty collections when not set."""
        mock_post.return_value = _make_mock_response()

        program = QiskitFunction(title="my-function", image="img:latest")

        _upload_with_docker_image(
            program=program,
            url=_UPLOAD_URL,
            token=_TOKEN,
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


class TestUploadWithArtifactPayload:
    """Tests that _upload_with_artifact sends the correct POST payload."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_payload_contains_all_fields(self, mock_post):
        """All fields from QiskitFunction are serialized correctly in the POST data."""
        mock_post.return_value = _make_mock_response(title="my-function", provider="my-provider")

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
            )

            _upload_with_artifact(
                program=program,
                url=_UPLOAD_URL,
                token=_TOKEN,
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
        assert data["arguments"] == json.dumps({})
        assert data["dependencies"] == json.dumps(["numpy", "scipy"])
        assert data["env_vars"] == json.dumps({"KEY": "VALUE"})
        assert data["description"] == "A test function"
        assert data["version"] == "2.0.0"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_optional_fields_default_correctly(self, mock_post):
        """Optional fields default to None / empty collections when not set."""
        mock_post.return_value = _make_mock_response()

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
                url=_UPLOAD_URL,
                token=_TOKEN,
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
        import pytest

        with tempfile.TemporaryDirectory() as working_dir:
            program = QiskitFunction(
                title="my-function",
                entrypoint="nonexistent.py",
                working_dir=working_dir,
            )
            with pytest.raises(QiskitServerlessException):
                _upload_with_artifact(
                    program=program,
                    url=_UPLOAD_URL,
                    token=_TOKEN,
                    span=MagicMock(),
                    client=MagicMock(),
                    instance=None,
                    channel=None,
                )

    @patch("qiskit_serverless.core.clients.serverless_client.requests.post")
    def test_artifact_tar_is_cleaned_up_after_upload(self, mock_post):
        """The temporary artifact.tar file is removed after a successful upload."""
        mock_post.return_value = _make_mock_response()

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
                url=_UPLOAD_URL,
                token=_TOKEN,
                span=MagicMock(),
                client=MagicMock(),
                instance=None,
                channel=None,
            )

            assert not os.path.exists(os.path.join(working_dir, "artifact.tar"))
