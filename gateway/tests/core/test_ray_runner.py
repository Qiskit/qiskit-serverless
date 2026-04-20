"""Tests for ray runner client functions."""

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import requests_mock
from django.conf import settings
from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase

from core.models import ComputeResource, Job, Program
from core.services.runners import get_runner
from core.services.runners.abstract_runner import RunnerError
from core.services.runners.ray_runner import RayRunner
from core.utils import encrypt_string


class response:
    status = "Success"
    metadata = client.V1ObjectMeta(name="test_user")


class mock_create(MagicMock):
    def create(self, namespace, body):
        return response()


class mock_delete(MagicMock):
    def delete(self, namespace, name):
        return response()


class TestRayRunner(APITestCase):
    """Tests for RayClient."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_submit_creates_cluster(self):
        """Tests that submit() creates K8s cluster and returns compute resource."""
        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_create()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        head_node_url = "http://test_user-head-svc:8265/"
        job = Job.objects.first()
        runner = get_runner(job)

        with (
            patch("core.services.runners.ray_runner._generate_resource_name", return_value="test_user"),
            patch("core.services.runners.ray_runner._create_cluster_data", return_value="dummy yaml file contents"),
            patch.object(runner, "_submit_to_ray", return_value="AwesomeJobId"),
            requests_mock.Mocker() as mocker,
        ):
            mocker.get(head_node_url, status_code=200)
            runner.submit()

            assert job.ray_job_id == "AwesomeJobId"
            assert "test_user" == job.compute_resource.title
            assert job.compute_resource.host == head_node_url
            assert not job.compute_resource._state.adding  # Saved to DB
            DynamicClient.resources.get.assert_called_once_with(api_version="v1", kind="RayCluster")

    def test_cleanup_cluster(self):
        """Tests cluster deletion."""
        namespace = settings.RAY_KUBERAY_NAMESPACE

        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_delete()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        client.CoreV1Api = MagicMock()

        job = Job.objects.first()
        job.compute_resource = ComputeResource.objects.create(
            title="some_cluster", host="http://some_cluster:8265/", owner=job.author
        )
        job.save()

        runner = get_runner(job)
        success = runner.free_resources()
        self.assertTrue(success)
        DynamicClient.resources.get.assert_any_call(api_version="v1", kind="RayCluster")
        DynamicClient.resources.get.assert_any_call(api_version="v1", kind="Certificate")
        client.CoreV1Api.assert_called()


class TestRayClientOperations(APITestCase):
    """Tests RayClient job operations (status, logs, stop, submit)."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self) -> None:
        super().setUp()
        self._temp_directory = tempfile.TemporaryDirectory()
        self.MEDIA_ROOT = self._temp_directory.name

        # prepare artifact file
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        path_to_media_artifact = os.path.join(self.MEDIA_ROOT, "awesome_artifact.tar")
        shutil.copyfile(path_to_resource_artifact, path_to_media_artifact)

    def tearDown(self):
        self._temp_directory.cleanup()
        super().tearDown()

    def test_job_status(self):
        """Tests job status."""
        job = Job.objects.first()
        job.ray_job_id = "AwesomeJobId"
        job.compute_resource = ComputeResource.objects.create(
            title="test_cluster", host="http://test:8265/", owner=job.author
        )
        job.save()

        mock_client = MagicMock()
        mock_client.get_job_status.return_value = JobStatus.PENDING

        runner = get_runner(job)
        runner._client = mock_client
        runner._connected = True

        job_status = runner.status()
        self.assertEqual(job_status, Job.PENDING)
        mock_client.get_job_status.assert_called_once_with("AwesomeJobId")

    def test_job_logs(self):
        """Tests job logs."""
        job = Job.objects.first()
        job.ray_job_id = "AwesomeJobId"
        job.compute_resource = ComputeResource.objects.create(
            title="test_cluster", host="http://test:8265/", owner=job.author
        )
        job.save()

        mock_client = MagicMock()
        mock_client.get_job_logs.return_value = "No logs yet."

        runner = get_runner(job)
        runner._client = mock_client
        runner._connected = True

        job_logs = runner.logs()
        self.assertEqual(job_logs, "No logs yet.")
        mock_client.get_job_logs.assert_called_once_with("AwesomeJobId")

    def test_job_stop(self):
        """Tests stopping of job."""
        job = Job.objects.first()
        job.ray_job_id = "AwesomeJobId"
        job.compute_resource = ComputeResource.objects.create(
            title="test_cluster", host="http://test:8265/", owner=job.author
        )
        job.save()

        mock_client = MagicMock()
        mock_client.stop_job.return_value = True

        runner = get_runner(job)
        runner._client = mock_client
        runner._connected = True

        is_job_stopped = runner.stop()
        self.assertTrue(is_job_stopped)
        mock_client.stop_job.assert_called_once_with("AwesomeJobId")

    def test_job_submit_local_mode(self):
        """Tests job submission in local mode (no K8s cluster creation)."""
        with self.settings(
            MEDIA_ROOT=self.MEDIA_ROOT,
            RAY_CLUSTER_MODE_LOCAL=True,
            RAY_LOCAL_HOST="http://localhost:8265/",
        ):
            job = Job.objects.first()
            job.env_vars = json.dumps({"ENV_JOB_GATEWAY_TOKEN": encrypt_string("awesome_token")})
            job.save()

            mock_ray_runner = MagicMock()
            mock_ray_runner.submit_job.return_value = "AwesomeJobId"

            runner = get_runner(job)

            with patch.object(runner, "_submit_to_ray", return_value="AwesomeJobId"):
                runner.submit()

                self.assertEqual(job.ray_job_id, "AwesomeJobId")
                self.assertIsNotNone(job.compute_resource)
                self.assertEqual(job.compute_resource.title, "Local compute resource")
                self.assertFalse(job.compute_resource._state.adding)  # Saved to DB


class TestGetRunner(APITestCase):
    """Tests runner factory selection."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_get_runner_returns_ray_runner(self):
        """Tests that get_runner returns a RayRunner for RAY jobs."""
        job = Job.objects.first()
        job.runner = Program.RAY

        runner = get_runner(job)

        self.assertIsInstance(runner, RayRunner)

    def test_get_runner_raises_for_fleets_runner(self):
        """Tests that get_runner raises RunnerError for unsupported FLEETS jobs."""
        job = Job.objects.first()
        job.runner = Program.FLEETS

        with self.assertRaises(RunnerError) as ctx:
            get_runner(job)

        self.assertIn("Fleets runner is not supported yet", str(ctx.exception))

    def test_get_runner_raises_for_unknown_runner(self):
        """Tests that get_runner raises RunnerError for unknown runner types."""
        job = Job.objects.first()
        job.runner = "unknown-runner"

        with self.assertRaises(RunnerError) as ctx:
            get_runner(job)

        self.assertEqual(str(ctx.exception), "Unknown runner type: unknown-runner")
