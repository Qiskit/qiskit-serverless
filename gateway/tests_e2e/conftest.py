"""
Pytest fixtures for e2e tests.
"""

import io
import os
import tarfile

import pytest

from tests_e2e.gateway_client import GatewayClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://127.0.0.1:8000")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")


def _validate_env():
    if not GATEWAY_TOKEN:
        raise RuntimeError("GATEWAY_TOKEN environment variable required")
    if not GATEWAY_INSTANCE:
        raise RuntimeError("TEST_CRN environment variable required")


_validate_env()


@pytest.fixture
def gateway_url():
    """Base URL for the gateway."""
    return GATEWAY_HOST


@pytest.fixture
def default_headers():
    """Default headers with authentication."""
    return create_headers(GATEWAY_TOKEN, GATEWAY_INSTANCE, GATEWAY_CHANNEL)


def create_headers(api_key: str, instance_crn: str, channel: str) -> dict[str, str]:
    """Create authentication headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Service-Channel": channel,
        "Service-CRN": instance_crn,
    }


@pytest.fixture
def client(gateway_url, default_headers) -> GatewayClient:
    """Gateway client with default configuration."""
    return GatewayClient(gateway_url, default_headers)
