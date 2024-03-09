"""Tests for serializer functions."""

import os
import json

from django.contrib.auth import models
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files import File
from rest_framework.test import APITestCase
from api.v1.serializers import JobConfigSerializer, UploadProgramSerializer
from api.models import JobConfig, Program


class SerializerTest(APITestCase):
    """Tests for serializer."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_JobConfigSerializer(self):
        data = '{"workers": null, "min_workers": 1, "max_workers": 5, "auto_scaling": true}'
        config_serializer = JobConfigSerializer(data=json.loads(data))
        assert config_serializer.is_valid()
        jobconfig = config_serializer.save()

        entry = JobConfig.objects.get(id=jobconfig.id)
        assert not entry.workers
        assert entry.min_workers == 1
        assert entry.max_workers == 5
        assert entry.auto_scaling

        data = '{"workers": 3, "min_workers": null, "max_workers": null, "auto_scaling": null}'
        config_serializer = JobConfigSerializer(data=json.loads(data))
        assert config_serializer.is_valid()
        jobconfig = config_serializer.save()

        entry = JobConfig.objects.get(id=jobconfig.id)
        assert entry.workers == 3
        assert not entry.min_workers
        assert not entry.max_workers
        assert not entry.auto_scaling

    def test_upload_program_serializer_creates_program(self):
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        data = File(open(path_to_resource_artifact, "rb"))
        upload_file = SimpleUploadedFile(
            "artifact.tar", data.read(), content_type="multipart/form-data"
        )

        user = models.User.objects.get(username="test_user")

        title = "Hello world"
        entrypoint = "pattern.py"
        env_vars = "{}"
        dependencies = "[]"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["env_vars"] = env_vars
        data["dependencies"] = dependencies
        data["artifact"] = upload_file

        serializer = UploadProgramSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        program: Program = serializer.save(author=user)
        self.assertEqual(title, program.title)
        self.assertEqual(entrypoint, program.entrypoint)
        self.assertEqual(env_vars, program.env_vars)
        self.assertEqual(dependencies, program.dependencies)

    def test_upload_program_serializer_fails_at_validation(self):
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        data = File(open(path_to_resource_artifact, "rb"))
        upload_file = SimpleUploadedFile(
            "artifact.tar", data.read(), content_type="multipart/form-data"
        )

        user = models.User.objects.get(username="test_user")

        title = "Hello world"
        entrypoint = "pattern.py"

        data = {}

        serializer = UploadProgramSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        errors = serializer.errors
        self.assertListEqual(["title", "entrypoint", "artifact"], list(errors.keys()))

        env_vars = {}
        dependencies = []
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["artifact"] = upload_file
        data["env_vars"] = env_vars
        data["dependencies"] = dependencies

        serializer = UploadProgramSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        errors = serializer.errors
        self.assertListEqual(["dependencies", "env_vars"], list(errors.keys()))
