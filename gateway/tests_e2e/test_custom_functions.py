"""Custom jobs e2e tests"""

from pytest import mark
import json
import requests


class TestCustomFunction:

    def test_custom_function_happy_path(self, client):
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

        status = client.wait_for_status(job_id)
        assert status == "SUCCEEDED"

        response = client.get_logs(job_id)
        response.raise_for_status()
        print("--- Logs ---------------------------")
        print(response.json()["logs"])
        print("------------------------------------")
        assert "[test] Results saved." in response.json()["logs"]

        response = client.get_results(job_id)
        response.raise_for_status()
        assert json.loads(response.json()["result"])["arguments"] == arguments

    def test_custom_function_broken(self, client):
        """Test a function with a compiler error"""
        function_title = "test-error-function"
        entrypoint = "program.py"

        # Function with a compile error: SyntaxError: invalid syntax
        artifact_tar = client.create_artifact_tar("""p r i n t ()""", entrypoint)

        client.upload(artifact_tar, entrypoint, function_title)
        response = client.run(function_title)
        job_id = response.json()["id"]

        status = client.wait_for_status(job_id)
        assert status == "FAILED"

        response = client.get_logs(job_id)
        print("--- Logs ---------------------------")
        print(response.json()["logs"])
        print("------------------------------------")
        assert "SyntaxError: invalid syntax" in response.json()["logs"]

        response = client.get_results(job_id)
        response.raise_for_status()
        assert response.json()["result"] is None
