"""
Pytest fixtures for e2e tests.
"""

import os

from pytest import fixture

from tests_e2e.gateway_client import GatewayClient

GATEWAY_TOKEN = os.environ.get("GATEWAY_TOKEN", "awesome_token")
GATEWAY_HOST = os.environ.get("GATEWAY_HOST", "http://localhost:8000")
GATEWAY_INSTANCE = os.environ.get("GATEWAY_INSTANCE", "an_awesome_crn")
GATEWAY_CHANNEL = os.environ.get("GATEWAY_CHANNEL", "ibm_quantum_platform")


@fixture
def gateway_url():
    """Base URL for the gateway."""
    return GATEWAY_HOST


@fixture
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


@fixture
def client(gateway_url, default_headers) -> GatewayClient:
    """Gateway client with default configuration."""
    return GatewayClient(gateway_url, default_headers)
