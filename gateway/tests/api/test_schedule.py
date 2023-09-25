"""Tests scheduling."""

from rest_framework.test import APITestCase
from unittest.mock import MagicMock, patch
import uuid, os, requests_mock, json


from api.models import Job, ComputeResource
from api.schedule import get_jobs_to_schedule_fair_share, execute_job
from api.ray import create_ray_cluster

from django.conf import settings
from django.contrib.auth import get_user_model

from kubernetes import client, config
from kubernetes.dynamic.client import DynamicClient


class response:
    status = "Success"
    metadata = client.V1ObjectMeta(name="test_user")


class mock_create(MagicMock):
    def create(self, namespace, body):
        return response()


class TestScheduleApi(APITestCase):
    """TestJobApi."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_get_fair_share_jobs(self):
        """Tests fair share jobs getter function."""
        jobs = get_jobs_to_schedule_fair_share(5)

        for job in jobs:
            self.assertIsInstance(job, Job)

        author_ids = [job.author_id for job in jobs]
        job_ids = [str(job.id) for job in jobs]
        self.assertTrue(1 in author_ids)
        self.assertTrue(4 in author_ids)
        self.assertEqual(len(jobs), 2)
        self.assertTrue("1a7947f9-6ae8-4e3d-ac1e-e7d608deec90" in job_ids)
        self.assertTrue("1a7947f9-6ae8-4e3d-ac1e-e7d608deec82" in job_ids)

    @patch("tarfile.open")
    @patch("tarfile.os.path.basename")
    @patch.object(uuid, "uuid4", return_value="")
    def test_already_created_ray_cluster_execute_job(
        self, mock_open, mock_basename, mock_uuid
    ):

        test_json = {"ray_version": "2.6.1"}

        test_post = {"job_id": "test_job_id", "submission_id": "test_submission_id"}

        config.load_incluster_config = MagicMock()
        client.api_client.ApiClient = MagicMock()
        DynamicClient.__init__ = lambda x, y: None
        DynamicClient.resources = MagicMock()
        mock = mock_create()
        DynamicClient.resources.get = MagicMock(return_value=mock)
        head_node_url = "http://test_user-head-svc:8265/"
        with requests_mock.Mocker() as mocker:
            mocker.get(head_node_url, status_code=200)
            user = get_user_model().objects.first()
            compute_resource = create_ray_cluster(
                user, "test_user", "dummy yaml file contents"
            )

            mocker.get(
                "http://test_user-head-svc:8265/api/version",
                status_code=200,
                json=test_json,
            )
            job = MagicMock()
            program = MagicMock()

            tar_path = os.path.join(settings.MEDIA_ROOT, "tmp", mock_uuid)
            mock_add = MagicMock()
            mock_open.add = mock_add
            mock_basename.return_value = tar_path

            program.dependencies = json.dumps({"packages": []})
            program.artifact = mock_basename
            program.entrypoint = "test_entrypoint"
            program.save()

            job.program = program
            job.author = user
            job.env_vars = json.dumps({"test": "test_env_vars"})
            job.compute_resource = compute_resource
            job.save()

            mocker.get(
                "http://test_user-head-svc:8265/api/packages/gcs/_ray_pkg_6068c19fb3b8530f.zip",
                status_code=200,
            )
            mocker.post(
                "http://test_user-head-svc:8265/api/jobs/",
                status_code=200,
                json=test_post,
            )
            retJob = execute_job(job)

        self.assertEqual(retJob.status, Job.PENDING)
        self.assertEqual(retJob.author, user)
        self.assertIsInstance(retJob.compute_resource, ComputeResource)
