import json
from unittest.mock import MagicMock
from rest_framework.test import APITestCase

from api.exceptions import ResourceNotFoundException
from api.v1.services import ProgramService, JobConfigService, JobService
from api.v1.serializers import ProgramSerializer, JobConfigSerializer
from api.models import Job, Program, JobConfig
from django.contrib.auth.models import User


class ServicesTest(APITestCase):
    """Tests for V1 services."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_save_program(self):
        """Test to verify that the service creates correctly an entry with its serializer."""

        user = User.objects.get(id=1)
        data = '{"title": "My Qiskit Pattern", "entrypoint": "pattern.py"}'
        program_serializer = ProgramSerializer(data=json.loads(data))
        program_serializer.is_valid()

        program = ProgramService.save(program_serializer, user, "path")
        entry = Program.objects.get(id=program.id)

        self.assertIsNotNone(entry)
        self.assertEqual(program.title, entry.title)

    def test_find_one_program_by_title(self):
        """The test must return one Program filtered by specific title."""

        user = User.objects.get(id=1)
        title = "Program"

        program = ProgramService.find_one_by_title(title, user)

        self.assertIsNotNone(program)
        self.assertEqual(program.title, title)

    def test_fail_to_find_program_by_title(self):
        """The test must raise a 404 exception when we don't find a Program with a specific title."""

        user = User.objects.get(id=1)
        title = "This Program doesn't exist"

        with self.assertRaises(ResourceNotFoundException):
            ProgramService.find_one_by_title(title, user)

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
        status = Job.QUEUED
        token = "42"
        carrier = {}
        jobconfig = None

        job = JobService.save(
            program=program,
            arguments=arguments,
            author=user,
            status=status,
            jobconfig=jobconfig,
            token=token,
            carrier=carrier,
        )

        self.assertIsNotNone(job)
        self.assertEqual(Job.objects.count(), 3)
