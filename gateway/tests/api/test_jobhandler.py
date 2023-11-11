"""Tests jobhandler."""

from rest_framework.test import APITestCase
import uuid

from api.models import Job
from api.jobhandler import throttle_job, schedule_job


class TestJobhandlerApi(APITestCase):
    """TestJobhandlerApi."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def test_throttle_job(self):
        """Tests throttle job."""
        job = Job.objects.get(id="1a7947f9-6ae8-4e3d-ac1e-e7d608deec89")
        job = throttle_job(job)
        self.assertEqual(job.id, uuid.UUID("1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"))

    # @patch("api.schedule.execute_job")
    # def test_schedule_job(self, execute_job):
    #    """Tests schedule job."""
    #    fake_job = MagicMock()
    #    fake_job.id = "1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"
    #    fake_job.logs = ""
    #    fake_job.status = "SUCCEEDED"
    #    fake_job.program.artifact.path = "non_existing_file.tar"
    #    fake_job.save.return_value = None
    #
    #    execute_job.return_value = fake_job
    #    schedule_job(uuid.UUID("1a7947f9-6ae8-4e3d-ac1e-e7d608deec82"))
    #    job_count = Job.objects.count()
    #    self.assertEqual(job_count, 7)
