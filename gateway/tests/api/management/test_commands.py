"""Tests for commands."""
from allauth.socialaccount.models import SocialApp
from django.core.management import call_command
from ray.dashboard.modules.job.common import JobStatus
from rest_framework.test import APITestCase
from unittest.mock import patch, MagicMock
from django.contrib.sites.models import Site

from api.models import ComputeResource, Job
from api.ray import JobHandler


class TestCommands(APITestCase):
    """Tests for commands."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_create_compute_resource(self):
        """Tests compute resource creation command."""
        call_command("create_compute_resource", "test_host")
        resources = ComputeResource.objects.all()
        self.assertTrue(
            "Ray cluster default" in [resource.title for resource in resources]
        )

    def test_free_resources(self):
        """Tests free resources command."""
        call_command("free_resources")
        num_resources = ComputeResource.objects.count()
        self.assertEqual(num_resources, 1)

    @patch("api.ray.get_job_handler")
    def test_update_jobs_statuses(self, get_job_handler):
        """Tests update of job statuses."""
        ray_client = MagicMock()
        ray_client.get_job_status.return_value = JobStatus.SUCCEEDED
        ray_client.get_job_logs.return_value = "No logs yet."
        ray_client.stop_job.return_value = True
        ray_client.submit_job.return_value = "AwesomeJobId"
        get_job_handler.return_value = JobHandler(ray_client)

        call_command("update_jobs_statuses")

        job = Job.objects.get(id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec84")
        self.assertEqual(job.status, "SUCCEEDED")

    def test_create_social_application(self):
        """Tests create social application command."""
        call_command(
            "create_social_application",
            host="social_app_host",
            client_id="social_app_client_id",
        )
        social_app = SocialApp.objects.get(provider="keycloak")
        site = Site.objects.get(name="social_app_host")
        self.assertEqual(social_app.client_id, "social_app_client_id")
        self.assertEqual(site.name, "social_app_host")

    @patch("api.schedule.execute_job")
    def test_schedule_queued_jobs(self, execute_job):
        """Tests schedule of queued jobs command."""
        execute_job.return_value = "Mocked job!"
        call_command("schedule_queued_jobs")
        # TODO: mock execute job to change status of job and query for QUEUED jobs  # pylint: disable=fixme
        job_count = Job.objects.count()
        self.assertEqual(job_count, 7)
