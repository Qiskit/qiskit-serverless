"""Gateway e2e tests"""

from pytest import mark
import json
import requests


class TestHappyPathTestE2E:
    def test_not_found(self, gateway_url):
        response = requests.get(f"{gateway_url}/XXX", timeout=10)
        assert response.status_code == 404

    def test_swagger_returns_200(self, gateway_url):
        response = requests.get(f"{gateway_url}/swagger/", timeout=10)
        response.raise_for_status()
        assert "<title>Gateway API</title>" in response.text

    @mark.skip(reason="TODO: specific User-Agent")
    def test_backoffice_return_200(self, gateway_url):
        response = requests.get(f"{gateway_url}/backoffice/login/", timeout=10)
        response.raise_for_status()
        assert "Django administration" in response.text

    def test_no_auth_header_returns_401(self, gateway_url):
        response = requests.get(f"{gateway_url}/api/v1/jobs/", timeout=10)
        print(f"\nGET {gateway_url}/api/v1/jobs/\n{response.text}")
        assert response.json().get("detail") == "Authorization token was not provided."
        assert response.status_code == 401

    def test_jobs(self, client):
        response = client.list_jobs()
        print(response.text)
        response.raise_for_status()
        return response.json()

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

    def test_custom_function(self, client):
        """Test complete lifecycle: upload -> get -> run -> status -> result -> logs"""
        function_title = "test-custom-function"
        entrypoint = "program.py"
        arguments = {"message": "foo", "number": 42}

        artifact_tar = client.create_artifact_tar(
            """
from qiskit_serverless import get_arguments, save_result
save_result({ "arguments": get_arguments() })
print("[test] Results saved.")
""",
            entrypoint,
        )

        response = client.upload(artifact_tar, entrypoint, function_title)
        response.raise_for_status()

        response = client.get_by_title(function_title)
        response.raise_for_status()

        response = client.list_programs()
        response.raise_for_status()
        assert any(p.get("title") == function_title for p in response.json())

        response = client.run(function_title, arguments)
        response.raise_for_status()
        job_id = response.json()["id"]

        response = client.list_jobs()
        response.raise_for_status()
        jobs = response.json()["results"]
        assert any(p["program"]["title"] == function_title for p in jobs)

        client.wait_for_status(job_id)

        response = client.get_logs(job_id)
        response.raise_for_status()
        print("--- Logs ---------------------------")
        print(response.json()["logs"])
        print("------------------------------------")
        assert "[test] Results saved." in response.json()["logs"]

        response = client.get_results(job_id)
        response.raise_for_status()
        assert json.loads(response.json()["result"])["arguments"] == arguments
