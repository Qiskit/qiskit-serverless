import json
from unittest.mock import MagicMock
from rest_framework.test import APITestCase

from api.exceptions import ResourceNotFoundException
from api.v1.services import JobConfigService, JobService
from api.v1.serializers import JobConfigSerializer
from api.models import Job, Program, JobConfig
from django.contrib.auth.models import User


class ServicesTest(APITestCase):
    """Tests for V1 services."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_create_job_config(self):
        """The test will create a job config with a basic configuration."""

        data = "{}"
        job_config_serializer = JobConfigSerializer(data=json.loads(data))
        job_config_serializer.is_valid()

        job_config = JobConfigService.save_with_serializer(job_config_serializer)
        entry = JobConfig.objects.get(id=job_config.id)

        self.assertIsNotNone(job_config)
        self.assertEqual(entry.id, job_config.id)

    def test_create_job(self):
        """Creating a job with basic consfiguration."""

        user = User.objects.get(id=1)
        program = Program.objects.get(pk="1a7947f9-6ae8-4e3d-ac1e-e7d608deec82")
        arguments = "{}"
        token = "42"
        carrier = {}
        jobconfig = None

        job = JobService.save(
            program=program,
            arguments=arguments,
            author=user,
            jobconfig=jobconfig,
            token=token,
            carrier=carrier,
        )

        self.assertIsNotNone(job)
        self.assertEqual(Job.objects.count(), 4)
        self.assertEqual(job.status, Job.QUEUED)
