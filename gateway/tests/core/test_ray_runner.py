"""Tests for ray runner client functions."""

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import requests
import requests_mock
from django.conf import settings
from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase

from django.contrib.auth.models import User

from core.models import ComputeResource, Job, Program
from core.services.runners import get_runner
from core.services.runners.abstract_runner import RunnerError
from core.services.runners.ray_runner import FilteredLogs, RayRunner
from core.utils import encrypt_string
from tests.utils import TestUtils


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
            assert job.compute_resource._state.adding  # Not saved to DB
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
        job.save()

        mock_client = MagicMock()
        mock_client.get_address.return_value = "http://test:8265"

        runner = get_runner(job)
        runner._client = mock_client
        runner._connected = True

        with requests_mock.Mocker() as m:
            m.get(
                "http://test:8265/api/jobs/AwesomeJobId/logs",
                text='{"logs": "No logs yet."}',
            )
            job_logs = runner.logs()

        self.assertEqual(list(job_logs.public_logs), ["No logs yet."])

    def _make_runner_with_mock_client(self, ray_job_id="AwesomeJobId", host="http://test:8265"):
        job = Job.objects.first()
        job.ray_job_id = ray_job_id
        job.save()
        mock_client = MagicMock()
        mock_client.get_address.return_value = host
        runner = get_runner(job)
        runner._client = mock_client
        runner._connected = True
        return runner

    def test_logs_retries_on_http_5xx_and_eventually_succeeds(self):
        """logs() retries up to 3 times on HTTP 5xx and returns logs on success."""
        runner = self._make_runner_with_mock_client()

        with requests_mock.Mocker() as m, patch("time.sleep"):
            m.get(
                "http://test:8265/api/jobs/AwesomeJobId/logs",
                response_list=[
                    {"status_code": 500},
                    {"status_code": 503},
                    {"text": '{"logs": "hello\\nworld"}'},
                ],
            )
            job_logs = runner.logs()

        self.assertEqual(list(job_logs.public_logs), ["hello", "world"])

    def test_logs_raises_runner_error_after_all_retries_exhausted(self):
        """logs() raises RunnerError after 3 consecutive HTTP 5xx responses."""
        runner = self._make_runner_with_mock_client()

        with requests_mock.Mocker() as m, patch("time.sleep"):
            m.get(
                "http://test:8265/api/jobs/AwesomeJobId/logs",
                response_list=[
                    {"status_code": 500},
                    {"status_code": 500},
                    {"status_code": 500},
                ],
            )
            with self.assertRaises(RunnerError):
                runner.logs()

    def test_logs_retries_on_mid_download_failure_and_eventually_succeeds(self):
        """logs() retries on mid-download failure and returns logs on success."""
        from collections import deque  # pylint: disable=import-outside-toplevel

        runner = self._make_runner_with_mock_client()

        with (
            patch.object(
                runner,
                "_stream_logs_from_ray",
                side_effect=[
                    requests.exceptions.ChunkedEncodingError("mid-download"),
                    FilteredLogs(public_logs=deque(["hello"]), private_logs=None),
                ],
            ) as mock_stream,
            patch("time.sleep"),
        ):
            job_logs = runner.logs()

        self.assertEqual(list(job_logs.public_logs), ["hello"])
        self.assertEqual(mock_stream.call_count, 2)

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
                self.assertTrue(job.compute_resource._state.adding)  # Not saved to DB


class TestGetRunner(APITestCase):
    """Tests runner factory selection."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_get_runner_returns_ray_runner(self):
        """Tests that get_runner returns a RayRunner for RAY jobs."""
        job = Job.objects.first()
        job.runner = Program.RAY

        runner = get_runner(job)

        self.assertIsInstance(runner, RayRunner)

    def test_get_runner_returns_fleets_runner(self):
        """Tests that get_runner returns a FleetsRunner for FLEETS jobs."""
        from core.services.runners.fleets_runner import FleetsRunner  # pylint: disable=import-outside-toplevel

        job = Job.objects.first()
        job.runner = Program.FLEETS

        runner = get_runner(job)

        self.assertIsInstance(runner, FleetsRunner)

    def test_get_runner_raises_for_unknown_runner(self):
        """Tests that get_runner raises RunnerError for unknown runner types."""
        job = Job.objects.first()
        job.runner = "unknown-runner"

        with self.assertRaises(RunnerError) as ctx:
            get_runner(job)

        self.assertEqual(str(ctx.exception), "Unknown runner type: unknown-runner")


class TestStreamLogsFromRay(APITestCase):
    """Tests that _stream_logs_from_ray classifies [PUBLIC]/[PRIVATE] lines correctly.

    These tests verify the filter logic that used to live in filter_logs.py:
    given a raw byte stream from Ray, the runner must strip prefixes and route
    each line to the correct deque (public_logs vs private_logs).
    """

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def _make_runner(self, job, host="http://test:8265"):
        mock_client = MagicMock()
        mock_client.get_address.return_value = host
        runner = RayRunner(job)
        runner._client = mock_client
        runner._connected = True
        return runner

    def _ray_response(self, content):
        """Build the JSON body that Ray dashboard returns for a log request.

        Ray JSON-encodes newlines as the two-byte sequence backslash-n inside
        the string value, so actual newlines in content are replaced accordingly.
        """
        return '{"logs": "' + content.replace("\n", "\\n") + '"}'

    def test_user_job_all_lines_go_to_public_prefixes_stripped(self):
        """User jobs: [PUBLIC], [PRIVATE], and untagged lines all go to public_logs, prefixes stripped."""
        job = Job.objects.first()
        job.ray_job_id = "ray-id"
        job.save()
        runner = self._make_runner(job)
        raw_logs = """
[PUBLIC] Public message
[PRIVATE] Private message

Unprefixed message
"""
        with requests_mock.Mocker() as m:
            m.get("http://test:8265/api/jobs/ray-id/logs", text=self._ray_response(raw_logs))
            result = runner.logs()

        self.assertEqual(list(result.public_logs), ["", "Public message", "Private message", "", "Unprefixed message"])
        self.assertIsNone(result.private_logs)

    def test_provider_job_classifies_public_and_private_correctly(self):
        """Provider jobs: [PUBLIC] → public_logs, [PRIVATE] and untagged → private_logs, prefixes stripped."""
        provider = TestUtils.get_or_create_provider("stream-test-provider")
        program = TestUtils.create_program(
            program_title="stream-test-program",
            author="stream-test-author",
            provider=provider,
        )
        job = TestUtils.create_job(author="stream-test-author", program=program, ray_job_id="ray-provider-id")
        runner = self._make_runner(job)
        raw_logs = """
[PUBLIC] INFO: Public log for user

[PRIVATE] INFO: Private log for provider only
[PUBLIC] INFO: Another public log
Internal system log
[PRIVATE] WARNING: Private warning
[PUBLIC] INFO: Final public log
"""
        with requests_mock.Mocker() as m:
            m.get("http://test:8265/api/jobs/ray-provider-id/logs", text=self._ray_response(raw_logs))
            result = runner.logs()

        self.assertEqual(
            list(result.public_logs),
            ["INFO: Public log for user", "INFO: Another public log", "INFO: Final public log"],
        )
        self.assertEqual(
            list(result.private_logs),
            ["", "", "INFO: Private log for provider only", "Internal system log", "WARNING: Private warning"],
        )
