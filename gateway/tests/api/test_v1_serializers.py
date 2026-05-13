"""Tests for serializer functions."""

import os
import json
import pytest
from unittest.mock import patch

from django.contrib.auth import models
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files import File
from django.core.management import call_command

from api.domain.authentication.channel import Channel
from api.v1.serializers import (
    JobConfigSerializer,
    JobSerializer,
    JobSerializerWithoutResult,
    UploadProgramSerializer,
    RunProgramSerializer,
    RunJobSerializer,
)
from core.domain.business_models import BusinessModel
from core.models import Job, JobConfig, Program
from tests.utils import TestUtils


class TestSerializers:
    """Tests for serializer."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, settings, db):
        call_command("loaddata", "tests/fixtures/fixtures.json")
        settings.MEDIA_ROOT = str(tmp_path)

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
        file_data = File(open(path_to_resource_artifact, "rb"))
        upload_file = SimpleUploadedFile("artifact.tar", file_data.read(), content_type="multipart/form-data")

        user = models.User.objects.get(username="test_user")

        title = "Hello world"
        entrypoint = "pattern.py"
        type = Program.CIRCUIT
        arguments = "{}"
        dependencies = "[]"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["type"] = type
        data["arguments"] = arguments
        data["dependencies"] = dependencies
        data["artifact"] = upload_file

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid()

        program: Program = serializer.save(author=user)
        assert title == program.title
        assert type == program.type
        assert entrypoint == program.entrypoint
        assert dependencies == program.dependencies

    def test_upload_program_serializer_check_empty_data(self):
        data = {}

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid()
        errors = serializer.errors
        assert ["title"] == list(errors.keys())

    def test_upload_program_serializer_fails_at_validation(self):
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        file_data = File(open(path_to_resource_artifact, "rb"))
        upload_file = SimpleUploadedFile("artifact.tar", file_data.read(), content_type="multipart/form-data")

        title = "Hello world"
        entrypoint = "pattern.py"
        arguments = {}
        dependencies = []

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["artifact"] = upload_file
        data["arguments"] = arguments
        data["dependencies"] = dependencies

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid()
        errors = serializer.errors
        assert ["dependencies"] == list(errors.keys())

    def test_upload_program_with_custom_image_and_provider(self):
        """Tests image upload serializer."""
        title = "Hello world"
        entrypoint = "main.py"
        arguments = {}
        dependencies = "[]"
        image = "docker.io/awesome/awesome-image:latest"
        provider = "default"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["arguments"] = arguments
        data["dependencies"] = dependencies
        data["image"] = image
        data["provider"] = provider

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid()
        assert "image" in list(serializer.validated_data.keys())

    def test_upload_program_with_custom_image_and_title_provider(self):
        """Tests image upload serializer."""
        title = "default/Hello world"
        entrypoint = "main.py"
        arguments = {}
        dependencies = "[]"
        image = "docker.io/awesome/awesome-image:latest"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["arguments"] = arguments
        data["dependencies"] = dependencies
        data["image"] = image

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid()
        assert "image" in list(serializer.validated_data.keys())

    def test_custom_image_without_provider(self):
        """Tests image upload serializer."""
        title = "Hello world"
        entrypoint = "main.py"
        arguments = {}
        dependencies = "[]"
        image = "docker.io/awesome/awesome-image:latest"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["arguments"] = arguments
        data["dependencies"] = dependencies
        data["image"] = image

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid()

    def test_run_program_serializer_check_emtpy_data(self):
        data = {}

        serializer = RunProgramSerializer(data=data)
        assert not serializer.is_valid()
        errors = serializer.errors
        assert ["title", "arguments", "config"] == list(errors.keys())

    def test_run_program_serializer_fails_at_validation(self):
        data = {
            "title": "Program",
            "arguments": {},
            "config": {},
        }

        serializer = RunProgramSerializer(data=data)
        assert not serializer.is_valid()
        errors = serializer.errors
        assert ["arguments"] == list(errors.keys())

    def test_run_program_serializer_config_json(self):
        assert_json = {
            "workers": None,
            "min_workers": 1,
            "max_workers": 5,
            "auto_scaling": True,
        }
        data = {
            "title": "Program",
            "arguments": "{}",
            "config": assert_json,
        }

        serializer = RunProgramSerializer(data=data)
        assert serializer.is_valid()

        config = serializer.data.get("config")
        assert type(assert_json) == type(config)
        assert assert_json == config

    def test_run_job_serializer_creates_job(self):
        user = models.User.objects.get(username="test_user")
        program_instance = Program.objects.get(id="1a7947f9-6ae8-4e3d-ac1e-e7d608deec82")
        arguments = "{}"

        config_data = {
            "workers": None,
            "min_workers": 1,
            "max_workers": 5,
            "auto_scaling": True,
        }
        config_serializer = JobConfigSerializer(data=config_data)
        config_serializer.is_valid()
        jobconfig = config_serializer.save()

        job_data = {"arguments": arguments, "program": program_instance.id}
        job_serializer = RunJobSerializer(data=job_data)
        job_serializer.is_valid()

        job = job_serializer.save(
            channel=Channel.IBM_QUANTUM_PLATFORM,
            author=user,
            carrier={},
            token="my_token",
            config=jobconfig,
            account_id="1234-5678-9012"
        )
        env_vars = json.loads(job.env_vars)

        assert job is not None
        assert job.program is not None
        assert job.arguments is not None
        assert job.config is not None
        assert job.author is not None
        assert not job.gpu
        assert not job.trial
        assert job.business_model == BusinessModel.SUBSIDIZED
        assert env_vars["PROGRAM_ENV1"] == "VALUE1"
        assert env_vars["PROGRAM_ENV2"] == "VALUE2"
        assert job.account_id == "1234-5678-9012"

    @patch("api.serializers.create_gpujob_allowlist")
    def test_run_job_serializer_sets_gpu_flag_for_gpu_provider(self, mock_gpujob_allowlist):
        """Tests that gpu flag is True when program's provider is in GPU allowlist."""
        mock_gpujob_allowlist.return_value = {"gpu-functions": {"gpu_provider": []}}

        user = models.User.objects.get(username="test_user")
        program = TestUtils.create_program(program_title="Default-Program", author=user, provider="gpu_provider")

        job_data = {"program": program.id}
        job_serializer = RunJobSerializer(data=job_data)
        job_serializer.is_valid()

        job = job_serializer.save(
            channel=Channel.IBM_QUANTUM_PLATFORM,
            author=user,
            carrier={},
            token="my_token",
        )

        assert job.gpu

    def test_upload_program_serializer_with_only_title(self):
        """Tests upload serializer with only title."""
        data = {"title": "awesome"}

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid()
        errors = serializer.errors
        assert ["non_field_errors"] == list(errors.keys())
        assert ["At least one of attributes (entrypoint, image) is required."] == [
            value[0] for value in errors.values()
        ]

    # Dependency validation tests use 'mergedeep' and 'ffsim' as representative examples
    # from requirements-dynamic-dependencies.txt. These tests validate the dependency
    # checking mechanism itself, not every individual production dependency.

    def test_upload_program_serializer_allowed_dependencies_basic(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["mergedeep"]'

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_allowed_dependencies_multi(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["mergedeep", "ffsim"]'

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_allowed_dependencies_versions(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["ffsim==0.0.60","mergedeep==1.3.4"]'

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_allowed_dependencies_objects(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '[{"ffsim":"0.0.60"},{"mergedeep":"==1.3.4"}]'

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_allowed_dependencies_mixed(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '[{"ffsim":"0.0.60"},"mergedeep==1.3.4"]'

        serializer = UploadProgramSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_blocked_dependency(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["notavailableone"]'

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_blocked_dependency_version(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["mergedeep==2.0.0"]'

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_blocked_dependency_object_version(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '[{"ffsim":"0.1.0"},{"mergedeep":"==1.0.0"}]'

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_blocked_dependency_operator(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '["mergedeep>=3.0.0"]'

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_malformed_dependency(self):
        data = {}
        data["title"] = "Hello world"
        data["entrypoint"] = "pattern.py"
        data["dependencies"] = '{"mergedeep": ">=3.0.0"}'

        serializer = UploadProgramSerializer(data=data)
        assert not serializer.is_valid(), serializer.errors

    def test_upload_program_serializer_updates_program_without_description(self):
        path_to_resource_artifact = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "resources",
            "artifact.tar",
        )
        file_data = File(open(path_to_resource_artifact, "rb"))
        upload_file = SimpleUploadedFile("artifact.tar", file_data.read(), content_type="multipart/form-data")

        user = models.User.objects.get(username="test_user")

        title = "Hello world"
        entrypoint = "pattern.py"
        arguments = "{}"
        dependencies = "[]"
        description = "This is my old description"

        data = {}
        data["title"] = title
        data["entrypoint"] = entrypoint
        data["arguments"] = arguments
        data["dependencies"] = dependencies
        data["description"] = description
        data["artifact"] = upload_file

        serializer = UploadProgramSerializer(data=data)
        serializer.is_valid()
        program: Program = serializer.save(author=user)
        assert description == program.description

        data_without_description = {}
        data_without_description["title"] = title
        data_without_description["entrypoint"] = entrypoint
        data_without_description["arguments"] = arguments
        data_without_description["dependencies"] = dependencies
        data_without_description["artifact"] = upload_file

        serializer_2 = UploadProgramSerializer(program, data=data_without_description)
        serializer_2.is_valid()
        program_2: Program = serializer_2.save(author=user)
        assert description == program_2.description

    def test_job_serializer_includes_fleet_id(self):
        """JobSerializer output includes fleet_id when set on the job."""
        user = models.User.objects.get(username="test_user")
        program = Program.objects.get(id="1a7947f9-6ae8-4e3d-ac1e-e7d608deec82")
        job = TestUtils.create_job(author=user, program=program, fleet_id="fleet-abc")

        data = JobSerializer(job).data
        assert "fleet_id" in data
        assert data["fleet_id"] == "fleet-abc"

    def test_job_serializer_without_result_includes_fleet_id(self):
        """JobSerializerWithoutResult output includes fleet_id when set on the job."""
        user = models.User.objects.get(username="test_user")
        program = Program.objects.get(id="1a7947f9-6ae8-4e3d-ac1e-e7d608deec82")
        job = TestUtils.create_job(author=user, program=program, fleet_id="fleet-xyz")

        data = JobSerializerWithoutResult(job).data
        assert "fleet_id" in data
        assert data["fleet_id"] == "fleet-xyz"
