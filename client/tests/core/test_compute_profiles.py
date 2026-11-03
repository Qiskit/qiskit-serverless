# This code is a Qiskit project.
#
# (C) Copyright IBM 2026.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for the client's compute-profiles methods: compute_profiles() and compute_profile()."""

import json
from unittest.mock import Mock, patch

import pytest

from qiskit_serverless import ComputeProfile
from qiskit_serverless.core.clients.serverless_client import ServerlessClient
from qiskit_serverless.exception import QiskitServerlessException

CATALOG = [
    {"compute_profile_id": "24x120", "cpu": "24", "memory": "120", "gpu": None},
    {"compute_profile_id": "24x120x1l40s", "cpu": "24", "memory": "120", "gpu": "1l40s"},
    {"compute_profile_id": "20x320x2a100", "cpu": "20", "memory": "320", "gpu": "2a100"},
]


@pytest.fixture
def mock_client():
    """A ServerlessClient whose constructor auth check is stubbed out."""
    mock_response = Mock()
    mock_response.ok = True
    mock_response.text = '{"status": "ok"}'
    mock_response.json.return_value = {"status": "ok"}

    with patch("qiskit_serverless.core.clients.serverless_client.requests.get", return_value=mock_response):
        return ServerlessClient(
            host="https://test-host.com",
            token="test-token",
            instance="test-instance",
            channel="ibm_quantum_platform",
            version="v1",
        )


def _stub_catalog(mock_get, catalog=None):
    """Point the mocked requests.get at a compute-profiles payload (defaults to CATALOG)."""
    if catalog is None:
        catalog = CATALOG
    mock_response = Mock()
    mock_response.ok = True
    mock_response.text = json.dumps(catalog)
    mock_response.json.return_value = catalog
    mock_get.return_value = mock_response


class TestComputeProfiles:
    """ServerlessClient.compute_profiles()."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_returns_profiles_and_calls_the_endpoint(self, mock_get, mock_client):
        """Builds ComputeProfile objects and hits the compute-profiles endpoint."""
        _stub_catalog(mock_get)

        profiles = mock_client.compute_profiles()

        assert all(isinstance(p, ComputeProfile) for p in profiles)
        assert {p.compute_profile_id for p in profiles} == {"24x120", "24x120x1l40s", "20x320x2a100"}
        call_url = mock_get.call_args[0][0] if mock_get.call_args[0] else mock_get.call_args[1]["url"]
        assert "compute-profiles" in call_url

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_prints_as_the_ordered_aligned_catalog(self, mock_get, mock_client):
        """Printing the result shows the formatted table without the caller iterating."""
        _stub_catalog(mock_get)

        assert str(mock_client.compute_profiles()) == (
            "24x120        (24 vCPU / 120 GB)\n"
            "24x120x1l40s  (24 vCPU / 120 GB / 1l40s)\n"
            "20x320x2a100  (20 vCPU / 320 GB / 2a100)"
        )

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_empty_catalog(self, mock_get, mock_client):
        """An empty catalog is an empty list that prints as an empty string."""
        _stub_catalog(mock_get, [])
        profiles = mock_client.compute_profiles()
        assert len(profiles) == 0
        assert str(profiles) == ""


class TestComputeProfile:
    """ServerlessClient.compute_profile() — validated single lookup."""

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_by_id(self, mock_get, mock_client):
        """A registered id returns that profile."""
        _stub_catalog(mock_get)
        assert mock_client.compute_profile("24x120").compute_profile_id == "24x120"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_by_fields_int_or_str_and_gpu(self, mock_get, mock_client):
        """cpu/memory match whether given as int or str; gpu omitted means CPU-only."""
        _stub_catalog(mock_get)
        assert mock_client.compute_profile(cpu=24, memory=120).compute_profile_id == "24x120"
        assert mock_client.compute_profile(cpu="24", memory="120").compute_profile_id == "24x120"
        assert mock_client.compute_profile(cpu=24, memory=120, gpu="1l40s").compute_profile_id == "24x120x1l40s"

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_no_match_raises_listing_available(self, mock_get, mock_client):
        """No exact match raises, and the message lists the available profiles."""
        _stub_catalog(mock_get)
        with pytest.raises(QiskitServerlessException) as exc_info:
            mock_client.compute_profile(cpu=24, memory=999)
        message = str(exc_info.value)
        assert "cpu=24, memory=999" in message
        assert "24x120        (24 vCPU / 120 GB)" in message

    @patch("qiskit_serverless.core.clients.serverless_client.requests.get")
    def test_gpu_must_match_exactly(self, mock_get, mock_client):
        """Specifying gpu that no registered profile has (at those cpu/memory) is not a match."""
        _stub_catalog(mock_get)
        with pytest.raises(QiskitServerlessException):
            mock_client.compute_profile(cpu=24, memory=120, gpu="8h100")

    def test_rejects_mixing_id_and_fields(self, mock_client):
        """Passing both an id and resources is rejected before any request."""
        with pytest.raises(QiskitServerlessException):
            mock_client.compute_profile("24x120", cpu=24)

    def test_rejects_no_arguments(self, mock_client):
        """Passing neither an id nor resources is rejected."""
        with pytest.raises(QiskitServerlessException):
            mock_client.compute_profile()
