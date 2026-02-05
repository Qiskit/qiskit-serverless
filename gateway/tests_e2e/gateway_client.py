import io
import json
import tarfile
import time
from io import BytesIO
from typing import Any

import requests
from requests import Response


class GatewayClient:
    """HTTP client for the Gateway API."""

    def __init__(self, base_url: str, headers: dict[str, str], timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.timeout = timeout

    @staticmethod
    def create_artifact_tar(source_code: str, entrypoint: str) -> io.BytesIO:
        """Create an in-memory tar file containing the program."""
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
            program_bytes = source_code.encode("utf-8")
            program_info = tarfile.TarInfo(name=entrypoint)
            program_info.size = len(program_bytes)
            tar.addfile(program_info, io.BytesIO(program_bytes))
        tar_buffer.seek(0)
        return tar_buffer

    def upload(
        self, artifact_tar: BytesIO, entrypoint: str, function_title: str
    ) -> Response:
        """Upload a function artifact."""
        response = requests.post(
            f"{self.base_url}/api/v1/programs/upload/",
            headers=self.headers,
            data={
                "title": function_title,
                "entrypoint": entrypoint,
                "arguments": json.dumps({}),
                "dependencies": json.dumps([]),
                "env_vars": json.dumps({}),
                "description": "E2E test function",
            },
            files={"artifact": ("artifact.tar", artifact_tar, "application/x-tar")},
            timeout=30,
        )
        print(f"upload: {response.text}")
        return response

    def get_by_title(self, function_title: str) -> Response:
        """Get a function by title."""
        response = requests.get(
            f"{self.base_url}/api/v1/programs/get_by_title/{function_title}",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"get_by_title: {response.text}")
        return response

    def run(
        self, function_title: str, arguments: dict[str, Any] | None = None
    ) -> Response:
        """Run a function and return the response."""
        response = requests.post(
            f"{self.base_url}/api/v1/programs/run/",
            headers=self.headers,
            json={
                "title": function_title,
                "arguments": json.dumps(arguments or {}),
                "config": {
                    "workers": None,
                    "min_workers": 1,
                    "max_workers": 5,
                    "auto_scaling": False,
                },
            },
            timeout=30,
        )
        print(f"run: {response.text}")
        return response

    def get_status(self, job_id: str) -> Response:
        """Get job status."""
        response = requests.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/",
            headers=self.headers,
            params={"with_result": "false"},
            timeout=self.timeout,
        )
        print(f"get_status: {response.text}")
        return response

    def wait_for_status(
        self,
        job_id: str,
        statuses: set[str] | None = None,
        timeout_seconds: int = 300,
        poll_interval: int = 1,
    ) -> str:
        """Wait for job to reach one of the specified statuses."""
        if statuses is None:
            statuses = {"SUCCEEDED", "FAILED", "STOPPED"}

        deadline = time.time() + timeout_seconds
        last_status = None
        while time.time() < deadline:
            response = requests.get(
                f"{self.base_url}/api/v1/jobs/{job_id}/",
                headers=self.headers,
                params={"with_result": "false"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            current_status = response.json()["status"]
            if current_status in statuses:
                print(current_status)  # newline at the end..
                return current_status
            elif current_status != last_status:
                print(current_status, end=".", flush=True)
                last_status = current_status
            else:
                print("", end=".", flush=True)

            time.sleep(poll_interval)

        print()  # newline before raising
        raise TimeoutError(f"Timeout waiting for job {job_id} to finish")

    def get_results(self, job_id: str) -> Response:
        """Get job results response"""
        response = requests.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/",
            headers=self.headers,
            params={"with_result": "true"},
            timeout=self.timeout,
        )
        print(f"get_results: {response.text}")
        return response

    def get_logs(self, job_id: str) -> Response:
        """Get job logs response"""
        response = requests.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/logs/",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"get_logs: {response.text}")
        return response

    def get_provider_logs(self, job_id: str) -> Response:
        """Get provider logs response"""
        response = requests.get(
            f"{self.base_url}/api/v1/jobs/{job_id}/provider-logs/",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"get_provider_logs: {response.text}")
        return response

    def list_jobs(self) -> Response:
        """List all jobs response"""
        response = requests.get(
            f"{self.base_url}/api/v1/jobs/",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"list_jobs: {response.text}")
        return response

    def list_programs(self) -> Response:
        """List all programs response"""
        response = requests.get(
            f"{self.base_url}/api/v1/programs/",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"list_programs: {response.text}")
        return response

    def get_dependencies_versions(self) -> Response:
        """Get dependencies versions response"""
        response = requests.get(
            f"{self.base_url}/api/v1/dependencies-versions/",
            headers=self.headers,
            timeout=self.timeout,
        )
        print(f"get_dependencies_versions: {response.text}")
        return response
