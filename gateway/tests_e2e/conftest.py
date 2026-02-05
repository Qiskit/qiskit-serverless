"""
Pytest fixtures for e2e tests.
"""

import io
import os
import tarfile

import pytest

from tests_e2e.gateway_client import GatewayClient

API_KEY = os.environ.get("TEST_API_KEY")
CRN = os.environ.get("TEST_CRN")
TEST_GATEWAY_URL = os.environ.get("TEST_GATEWAY_URL", "http://127.0.0.1:8000")
CHANNEL = os.environ.get("TEST_CHANNEL", "ibm_quantum_platform")


def _validate_env():
    if not API_KEY:
        raise RuntimeError("TEST_API_KEY environment variable required")
    if not CRN:
        raise RuntimeError("TEST_CRN environment variable required")


_validate_env()


@pytest.fixture
def gateway_url():
    """Base URL for the gateway."""
    return TEST_GATEWAY_URL


@pytest.fixture
def default_headers():
    """Default headers with authentication."""
    return create_headers(API_KEY, CRN, CHANNEL)


def create_headers(api_key: str, instance_crn: str, channel: str) -> dict[str, str]:
    """Create authentication headers."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Service-Channel": channel,
        "Service-CRN": instance_crn,
    }


@pytest.fixture
def client(gateway_url, default_headers):
    """Gateway client with default configuration."""
    return GatewayClient(gateway_url, default_headers)
