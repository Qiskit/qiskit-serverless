"""Smoke tests"""

from pytest import mark
import requests


class TestSmokeTests:
    def test_not_found(self, gateway_url):
        response = requests.get(f"{gateway_url}/XXX", timeout=10)
        assert response.status_code == 404

    def test_swagger(self, gateway_url):
        response = requests.get(f"{gateway_url}/swagger/", timeout=10)
        response.raise_for_status()
        assert "<title>Gateway API</title>" in response.text

    def test_auth_missing(self, gateway_url):
        response = requests.get(f"{gateway_url}/api/v1/jobs/", timeout=10)
        print(response.text)

        assert response.json().get("detail") == "Authorization token was not provided."
        assert response.status_code == 401

    def test_jobs(self, client):
        response = client.list_jobs()
        print(response.text)
        response.raise_for_status()

        versions = response.json()
        assert isinstance(versions["results"], list)

    def test_program_list(self, client):
        response = client.list_programs()
        print(response.text)
        response.raise_for_status()

        programs = response.json()
        assert isinstance(programs, list)

    def test_dependencies_versions(self, client):
        response = client.get_dependencies_versions()
        print(response.text)
        response.raise_for_status()

        versions = response.json()
        assert isinstance(versions, list)
