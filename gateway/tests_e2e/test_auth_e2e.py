"""
Gateway e2e tests (localhost, docker, staging, pro)

"""

import os

import requests

API_KEY = os.environ.get("TEST_API_KEY")
CRN = os.environ.get("TEST_CRN")
GATEWAY_URL = os.environ.get("TEST_GATEWAY_URL", "http://127.0.0.1:8000")
CHANNEL = os.environ.get("TEST_CHANNEL", "ibm_quantum_platform")

if not API_KEY:
    raise RuntimeError("TEST_API_KEY environment variable required")
if not CRN:
    raise RuntimeError("TEST_CRN environment variable required")

AUTH_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Service-Channel": CHANNEL,
    "Service-CRN": CRN,
}


class TestHappyPathTestE2E:
    """E2E smoke tests"""

    def test_swagger(self):
        # swagger no auth
        response = requests.get(f"{GATEWAY_URL}/swagger/", timeout=10)
        assert response.status_code == 200

    def test_no_auth_header_returns_401(self):
        response = requests.get(f"{GATEWAY_URL}/api/v1/jobs/", timeout=10)
        assert response.status_code == 401

    def test_jobs(self):
        response = requests.get(
            f"{GATEWAY_URL}/api/v1/jobs/",
            headers=AUTH_HEADERS,
            timeout=10,
        )
        assert response.status_code == 200
        assert "results" in response.json()

    def test_program_list(self):
        response = requests.get(
            f"{GATEWAY_URL}/api/v1/programs/", headers=AUTH_HEADERS, timeout=10
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_dependencies_versions(self):
        response = requests.get(
            f"{GATEWAY_URL}/api/v1/dependencies-versions/",
            headers=AUTH_HEADERS,
            timeout=10,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
