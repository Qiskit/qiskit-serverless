"""Tests for ray util functions."""

import json
import os
import shutil
from unittest.mock import MagicMock

import requests_mock
from django.conf import settings
from django.contrib.auth import get_user_model
from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase

from api.models import ComputeResource, Job
from api.ray import (
    create_compute_resource,
    kill_ray_cluster,
    JobHandler,
)
from api.utils import encrypt_string


class response:
    status = "Success"
    metadata = client.V1ObjectMeta(name="test_user")


class mock_create(MagicMock):
    def create(self, namespace, body):
        return response()


class mock_delete(MagicMock):
    def delete(self, namespace, name):
        return response()


class TestRayUtils(APITestCase):
    """Tests for ray utils."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_cluster(self):
        """Tests for cluster creation."""
        namespace = settings.RAY_KUBERAY_NAMESPACE
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
            compute_resource = create_compute_resource(
                job, "test_user", "dummy yaml file contents"
            )
            self.assertIsInstance(compute_resource, ComputeResource)
            self.assertEqual(job.author.username, compute_resource.title)
            self.assertEqual(compute_resource.host, head_node_url)
            DynamicClient.resources.get.assert_called_once_with(
                api_version="v1", kind="RayCluster"
            )

    def test_kill_cluster(self):
        """Tests cluster deletion."""
        namespace = settings.RAY_KUBERAY_NAMESPACE

        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_delete()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        client.CoreV1Api = MagicMock()

        success = kill_ray_cluster("some_cluster")
        self.assertTrue(success)
        DynamicClient.resources.get.assert_any_call(api_version="v1", kind="RayCluster")
        DynamicClient.resources.get.assert_any_call(
            api_version="v1", kind="Certificate"
        )
        client.CoreV1Api.assert_called()


class TestJobHandler(APITestCase):
    """Tests job handler."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self) -> None:
        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.PENDING
        ray_client.get_job_logs.return_value = "No logs yet."
        ray_client.stop_job.return_value = True
        ray_client.submit_job.return_value = "AwesomeJobId"
        self.handler = JobHandler(ray_client)

        # prepare artifact file
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        path_to_media_artifact = os.path.join(
            settings.MEDIA_ROOT, "awesome_artifact.tar"
        )
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        shutil.copyfile(path_to_resource_artifact, path_to_media_artifact)

    def test_job_status(self):
        """Tests job status."""
        job_status = self.handler.status("AwesomeJobId")
        self.assertTrue(job_status in JobStatus)

    def test_job_logs(self):
        """Tests job logs."""
        job_logs = self.handler.logs("AwesomeJobId")
        self.assertEqual(job_logs, "No logs yet.")

    def test_job_stop(self):
        """Tests stopping of job."""
        is_job_stopped = self.handler.stop("AwesomeJobId")
        self.assertTrue(is_job_stopped)

    def test_job_submit(self):
        """Tests job submission."""
        job = Job.objects.first()
        job.env_vars = json.dumps(
            {"ENV_JOB_GATEWAY_TOKEN": encrypt_string("awesome_token")}
        )
        job_id = self.handler.submit(job)
        self.assertEqual(job_id, "AwesomeJobId")
