"""Tests for ray util functions."""

import json
import os
import shutil
from unittest.mock import MagicMock, patch

import pytest
import requests_mock
from django.core.management import call_command
from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient
from ray.dashboard.modules.job.common import JobStatus

from core.models import ComputeResource, Job
from core.utils import encrypt_string
from core.services.runners.ray_runner import RayRunner, _kill_ray_cluster


class response:
    status = "Success"
    metadata = client.V1ObjectMeta(name="test_user")


class mock_create(MagicMock):
    def create(self, namespace=None, body=None):
        return response()


class mock_delete(MagicMock):
    def delete(self, namespace=None, name=None):
        return response()


class TestRayUtils:
    """Tests for ray utils."""

    @pytest.fixture(autouse=True)
    def _setup(self, db):
        call_command("loaddata", "tests/fixtures/schedule_fixtures.json")

    def test_create_cluster(self):
        """Tests for cluster creation."""
        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_create()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        head_node_url = "http://test_user-head-svc:8265/"
        job = Job.objects.first()
        with requests_mock.Mocker() as mocker:
            mocker.get(head_node_url, status_code=200)
            with patch(
                "core.services.runners.ray_runner._generate_resource_name",
                return_value="test_user",
            ):
                with patch(
                    "core.services.runners.ray_runner._create_cluster_data",
                    return_value={},
                ):
                    runner = RayRunner(job)
                    host, cluster_name = runner._create_k8s_cluster()
                    assert host == head_node_url
                    assert cluster_name == "test_user"
                    DynamicClient.resources.get.assert_called_once_with(api_version="v1", kind="RayCluster")

    def test_kill_cluster(self):
        """Tests cluster deletion."""
        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_delete()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        client.CoreV1Api = MagicMock()

        success = _kill_ray_cluster("some_cluster")
        assert success
        DynamicClient.resources.get.assert_any_call(api_version="v1", kind="RayCluster")
        DynamicClient.resources.get.assert_any_call(api_version="v1", kind="Certificate")
        client.CoreV1Api.assert_called()


class TestRayRunner:
    """Tests ray runner."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        call_command("loaddata", "tests/fixtures/schedule_fixtures.json")
        settings.MEDIA_ROOT = str(tmp_path)

        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.PENDING
        ray_client.get_address.return_value = "http://test:8265"
        ray_client.stop_job.return_value = True
        ray_client.submit_job.return_value = "AwesomeJobId"

        job = Job.objects.first()
        self.handler = RayRunner(job)
        self.handler._client = ray_client
        self.handler._connected = True
        self.ray_client = ray_client

        # prepare artifact file
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        path_to_media_artifact = os.path.join(str(tmp_path), "awesome_artifact.tar")
        shutil.copyfile(path_to_resource_artifact, path_to_media_artifact)

    def test_job_status(self):
        """Tests job status."""
        job_status = self.handler.status()
        assert job_status == Job.PENDING

    def test_job_logs(self):
        """Tests job logs."""
        self.handler._job.ray_job_id = "AwesomeJobId"
        with requests_mock.Mocker() as m:
            m.get("http://test:8265/api/jobs/AwesomeJobId/logs", text="No logs yet.")
            job_logs = self.handler.logs()
        assert job_logs == "No logs yet."

    def test_job_stop(self):
        """Tests stopping of job."""
        is_job_stopped = self.handler.stop()
        assert is_job_stopped

    def test_job_submit(self, settings):
        """Tests job submission."""
        settings.RAY_CLUSTER_MODE_LOCAL = True
        job = self.handler.job
        job.env_vars = json.dumps({"ENV_JOB_GATEWAY_TOKEN": encrypt_string("awesome_token")})
        with patch("core.services.runners.ray_runner.JobSubmissionClient") as mock_client_cls:
            mock_client_cls.return_value = self.ray_client
            self.handler.submit()
        assert isinstance(job.compute_resource, ComputeResource)
        assert job.ray_job_id == "AwesomeJobId"
