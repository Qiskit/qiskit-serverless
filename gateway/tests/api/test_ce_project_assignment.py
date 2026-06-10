"""Tests for CodeEngineProject assignment to Program."""

from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from api.domain.authentication.channel import Channel
from api.serializers import RunJobSerializer, UploadProgramSerializer
from core.models import CodeEngineProject, Program
from core.services.runners import RunnerError
from core.services.runners.fleets_runner import FleetsRunner
from tests.utils import TestUtils


@pytest.mark.django_db
class TestCEProjectAssignmentAtUpload:
    """Verify CE project is assigned to Fleets programs at creation via TestUtils."""

    @pytest.fixture
    def ce_project(self):
        """Create an active CodeEngineProject."""
        return TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )

    def test_fleets_program_gets_ce_project(self, ce_project):
        """Fleets programs are created with a CE project."""
        program = TestUtils.create_program(
            program_title="new-fleets-func",
            author="uploader",
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )
        assert program.code_engine_project == ce_project

    def test_ray_program_does_not_get_ce_project(self, ce_project):
        """Ray programs do not have a CE project."""
        program = TestUtils.create_program(
            program_title="new-ray-func",
            author="uploader",
            runner=Program.RAY,
        )
        assert program.code_engine_project is None

    def test_fleets_program_without_project_has_none(self):
        """Fleets program created without CE project has None."""
        program = TestUtils.create_program(
            program_title="orphan-func",
            author="uploader",
            runner=Program.FLEETS,
        )
        assert program.code_engine_project is None


@pytest.mark.django_db
class TestCEProjectResolutionViaSerializer:
    """Verify CE project resolution via the serializer create/update paths."""

    @pytest.fixture
    def ce_project(self):
        """Create the active CodeEngineProject."""
        return TestUtils.get_or_create_ce_project(
            project_name="default-project",
            project_id="default-ce-project-id",
            cos_bucket_user_data_name="default-user-bucket",
            cos_bucket_provider_data_name="default-provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )

    @pytest.fixture(autouse=True)
    def _use_default_project_name(self, settings):
        """Set CE_DEFAULT_PROJECT_NAME for all tests in this class."""
        settings.CE_DEFAULT_PROJECT_NAME = "default-project"

    def test_create_fleets_program_gets_default_project(self, ce_project):
        """Fleets program created via serializer gets the active CE project."""
        user, _ = TestUtils.get_user_and_username("uploader")
        serializer = UploadProgramSerializer()
        program = serializer.create(
            {
                "title": "fleets-func",
                "author": user,
                "runner": Program.FLEETS,
                "entrypoint": "main.py",
                "dependencies": "[]",
            }
        )

        assert program.code_engine_project == ce_project

    def test_update_ray_to_fleets_gets_default_project(self, ce_project):
        """Re-uploading a Ray program as Fleets assigns the default CE project."""
        user, _ = TestUtils.get_user_and_username("uploader")
        program = TestUtils.create_program(
            program_title="ray-to-fleets",
            author=user,
            runner=Program.RAY,
        )
        assert program.code_engine_project is None

        serializer = UploadProgramSerializer()
        updated = serializer.update(
            program,
            {
                "entrypoint": "main.py",
                "dependencies": "[]",
                "runner": Program.FLEETS,
                "author": user,
            },
        )

        assert updated.code_engine_project == ce_project

    def test_select_default_raises_without_config(self, settings):
        """select_default raises ValueError when CE_DEFAULT_PROJECT_NAME is empty."""
        settings.CE_DEFAULT_PROJECT_NAME = ""
        with pytest.raises(ValueError, match="CE_DEFAULT_PROJECT_NAME not configured"):
            CodeEngineProject.objects.select_default()


@pytest.mark.django_db
class TestJobCreationValidation:
    """Verify job creation validates CE project presence on program."""

    @pytest.fixture
    def ce_project(self):
        """Create an active CodeEngineProject."""
        return TestUtils.get_or_create_ce_project(
            project_name="test-project",
            project_id="test-ce-project-id",
            cos_bucket_user_data_name="user-bucket",
            cos_bucket_provider_data_name="provider-bucket",
            cos_instance_name="cos-instance",
            cos_key_name="cos-key",
        )

    @patch("api.serializers.get_arguments_storage")
    def test_job_creation_succeeds_with_ce_project(self, mock_storage, ce_project):
        """Job creation succeeds when Fleets program has a CE project."""
        user, _ = TestUtils.get_user_and_username("runner")
        program = TestUtils.create_program(
            program_title="good-func",
            author=user,
            runner=Program.FLEETS,
            code_engine_project=ce_project,
        )

        serializer = RunJobSerializer(data={"program": program.id})
        serializer.is_valid(raise_exception=True)
        job = serializer.save(
            channel=Channel.IBM_QUANTUM_PLATFORM,
            author=user,
            carrier={},
            token="my_token",
        )

        assert job.program.code_engine_project == ce_project
        assert job.runner == Program.FLEETS
        assert job.ce_project_name == ce_project.project_name
        assert job.ce_region == ce_project.region

    def test_job_creation_fails_without_ce_project(self):
        """Job creation raises ValidationError when Fleets program lacks CE project."""
        user, _ = TestUtils.get_user_and_username("runner")
        program = TestUtils.create_program(
            program_title="orphan-func",
            author=user,
            runner=Program.FLEETS,
        )

        serializer = RunJobSerializer(data={"program": program.id})
        serializer.is_valid(raise_exception=True)

        with pytest.raises(ValidationError, match="no Code Engine project assigned"):
            serializer.save(
                channel=Channel.IBM_QUANTUM_PLATFORM,
                author=user,
                carrier={},
                token="my_token",
            )

    def test_ray_job_creation_does_not_require_ce_project(self):
        """Ray jobs do not need a CE project and create successfully without one."""
        user, _ = TestUtils.get_user_and_username("runner")
        program = TestUtils.create_program(
            program_title="ray-func",
            author=user,
            runner=Program.RAY,
        )

        serializer = RunJobSerializer(data={"program": program.id})
        serializer.is_valid(raise_exception=True)
        job = serializer.save(
            channel=Channel.IBM_QUANTUM_PLATFORM,
            author=user,
            carrier={},
            token="my_token",
        )

        assert job.runner == Program.RAY
        assert job.program.code_engine_project is None


@pytest.mark.django_db
class TestDeletedProgramHandling:
    """Verify FleetsRunner handles deleted program gracefully."""

    def test_fleets_runner_raises_runner_error_when_program_is_none(self):
        """FleetsRunner._get_project raises RunnerError when program was deleted."""
        user, _ = TestUtils.get_user_and_username("runner")
        program = TestUtils.create_program(
            program_title="to-delete",
            author=user,
            runner=Program.FLEETS,
        )
        job = TestUtils.create_job(author=user, program=program)
        program.delete()
        job.refresh_from_db()

        runner = FleetsRunner(job)
        with pytest.raises(RunnerError, match="has been deleted"):
            runner._get_project()  # pylint: disable=protected-access
