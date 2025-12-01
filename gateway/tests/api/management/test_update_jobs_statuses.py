"""Unit tests for update_jobs_statuses command."""

from datetime import datetime
from unittest.mock import MagicMock, patch, call
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase
from concurrency.exceptions import RecordModifiedError
from ray.dashboard.modules.job.common import JobStatus

from api.models import Job, ComputeResource
from api.management.commands.update_jobs_statuses import update_job_status, Command


class TestUpdateJobStatus(APITestCase):
    """Tests for update_job_status function."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self):
        """Set up test fixtures."""
        self.job = Job.objects.get(id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec84")
        self.job.created = datetime.now()
        self.job.save()

    def test_update_job_status_no_compute_resource(self):
        """Test job without compute resource is skipped."""
        job = Job.objects.create(
            author_id=1,
            status=Job.PENDING,
            compute_resource=None,
        )

        result = update_job_status(job)

        self.assertFalse(result)
        self.assertEqual(job.status, Job.PENDING)

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_success(self, mock_get_handler):
        """Test successful job status update."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = "Job is running"
        mock_get_handler.return_value = mock_handler

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.RUNNING)
        self.assertEqual(self.job.logs, "Job is running")

    @patch(
        "api.management.commands.update_jobs_statuses.handle_job_status_not_available"
    )
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_runtime_error_on_status(
        self, mock_get_handler, mock_handle_not_available
    ):
        """Test job status update when RuntimeError occurs on status fetch."""
        mock_handler = MagicMock()
        mock_handler.status.side_effect = RuntimeError("Connection lost")
        mock_get_handler.return_value = mock_handler
        mock_handle_not_available.return_value = Job.FAILED

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.FAILED)

    @patch(
        "api.management.commands.update_jobs_statuses.handle_job_status_not_available"
    )
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_no_handler(
        self, mock_get_handler, mock_handle_not_available
    ):
        """Test job status update when handler is None."""
        mock_get_handler.return_value = None
        mock_handle_not_available.return_value = Job.FAILED

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.FAILED)

    @patch("api.management.commands.update_jobs_statuses.check_job_timeout")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_timeout(self, mock_get_handler, mock_timeout):
        """Test job status update when job times out."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = "Running logs"
        mock_get_handler.return_value = mock_handler
        mock_timeout.return_value = True

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.STOPPED)

    @patch(
        "api.management.commands.update_jobs_statuses.handle_job_status_not_available"
    )
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_not_available(self, mock_get_handler, mock_handle):
        """Test job status update when status is not available."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = None
        mock_get_handler.return_value = mock_handler
        mock_handle.return_value = Job.FAILED

        result = update_job_status(self.job)

        self.assertTrue(result)
        mock_handle.assert_called_once()

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_terminal_state_cleanup(self, mock_get_handler):
        """Test env_vars and sub_status cleanup in terminal state."""
        self.job.env_vars = '{"token": "secret"}'
        self.job.sub_status = Job.MAPPING

        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.SUCCEEDED
        mock_handler.logs.return_value = "Success"
        mock_get_handler.return_value = mock_handler

        update_job_status(self.job)

        self.assertEqual(self.job.status, Job.SUCCEEDED)
        self.assertEqual(self.job.env_vars, "{}")
        self.assertIsNone(self.job.sub_status)

    @patch(
        "api.management.commands.update_jobs_statuses.fail_job_insufficient_resources"
    )
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_insufficient_resources(
        self, mock_get_handler, mock_fail
    ):
        """Test job fails when insufficient resources detected in logs."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = (
            "Error: No available node types can fulfill resource request"
        )
        mock_get_handler.return_value = mock_handler
        mock_fail.return_value = Job.FAILED

        update_job_status(self.job)

        self.assertEqual(self.job.status, Job.FAILED)
        self.assertEqual(self.job.env_vars, "{}")
        mock_fail.assert_called_once_with(self.job)

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_logs_runtime_error(self, mock_get_handler):
        """Test job status update when RuntimeError occurs on logs fetch."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.side_effect = RuntimeError("Cannot fetch logs")
        mock_get_handler.return_value = mock_handler

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.RUNNING)

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_no_status_change(self, mock_get_handler):
        """Test job status update when status doesn't change."""
        self.job.status = Job.RUNNING
        self.job.save()

        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = "Still running"
        mock_get_handler.return_value = mock_handler

        result = update_job_status(self.job)

        self.assertFalse(result)
        self.assertEqual(self.job.status, Job.RUNNING)

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_record_modified_error(self, mock_get_handler):
        """Test job status update handles RecordModifiedError."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.SUCCEEDED
        mock_handler.logs.return_value = "Done"
        mock_get_handler.return_value = mock_handler

        with patch.object(
            self.job, "save", side_effect=RecordModifiedError(target=self.job)
        ):
            result = update_job_status(self.job)

        self.assertTrue(result)

    @patch("api.management.commands.update_jobs_statuses.check_logs")
    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_check_logs_called(
        self, mock_get_handler, mock_check_logs
    ):
        """Test check_logs is called with correct parameters."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = "Raw logs"
        mock_get_handler.return_value = mock_handler
        mock_check_logs.return_value = "Checked logs"

        update_job_status(self.job)

        mock_check_logs.assert_called_once_with("Raw logs", self.job)
        self.assertEqual(self.job.logs, "Checked logs")


class TestUpdateJobsStatusesCommand(APITestCase):
    """Tests for Command class."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self):
        """Set up test fixtures."""
        self.job = Job.objects.get(id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec84")
        self.job.created = datetime.now()
        self.job.save()

    @override_settings(LIMITS_MAX_CLUSTERS=1, LIMITS_GPU_CLUSTERS=0)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_updates_classical_jobs_only(self, mock_update):
        """Test command updates only classical jobs when GPU clusters disabled."""
        mock_update.return_value = True

        call_command("update_jobs_statuses")

        # Should be called for classical jobs only
        self.assertTrue(mock_update.called)
        called_jobs = [call_args[0][0] for call_args in mock_update.call_args_list]
        for job in called_jobs:
            self.assertFalse(job.gpu)

    @override_settings(LIMITS_MAX_CLUSTERS=0, LIMITS_GPU_CLUSTERS=1)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_updates_gpu_jobs_only(self, mock_update):
        """Test command updates only GPU jobs when classical clusters disabled."""
        # Create a GPU job
        gpu_job = Job.objects.create(
            author_id=1,
            status=Job.PENDING,
            gpu=True,
            compute_resource=self.job.compute_resource,
        )
        mock_update.return_value = True

        call_command("update_jobs_statuses")

        # Should be called for GPU jobs only
        self.assertTrue(mock_update.called)
        called_jobs = [call_args[0][0] for call_args in mock_update.call_args_list]
        for job in called_jobs:
            self.assertTrue(job.gpu)

    @override_settings(LIMITS_MAX_CLUSTERS=1, LIMITS_GPU_CLUSTERS=1)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_updates_both_job_types(self, mock_update):
        """Test command updates both classical and GPU jobs."""
        # Create a GPU job
        gpu_job = Job.objects.create(
            author_id=1,
            status=Job.PENDING,
            gpu=True,
            compute_resource=self.job.compute_resource,
        )
        mock_update.return_value = True

        call_command("update_jobs_statuses")

        # Should be called for both types
        self.assertTrue(mock_update.called)
        self.assertGreaterEqual(mock_update.call_count, 2)

    @override_settings(LIMITS_MAX_CLUSTERS=0, LIMITS_GPU_CLUSTERS=0)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_no_updates_when_all_disabled(self, mock_update):
        """Test command doesn't update when all clusters disabled."""
        call_command("update_jobs_statuses")

        mock_update.assert_not_called()

    @override_settings(LIMITS_MAX_CLUSTERS=1, LIMITS_GPU_CLUSTERS=0)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_counts_updated_jobs(self, mock_update):
        """Test command correctly counts updated jobs."""
        mock_update.side_effect = [True, False, True]

        call_command("update_jobs_statuses")

        # Should count only jobs that returned True
        self.assertEqual(mock_update.call_count, 3)

    @override_settings(LIMITS_MAX_CLUSTERS=1, LIMITS_GPU_CLUSTERS=0)
    @patch("api.management.commands.update_jobs_statuses.update_job_status")
    def test_command_filters_running_statuses(self, mock_update):
        """Test command only processes jobs with RUNNING_STATUSES."""
        # Create jobs with different statuses
        Job.objects.create(
            author_id=1,
            status=Job.SUCCEEDED,
            compute_resource=self.job.compute_resource,
        )
        Job.objects.create(
            author_id=1,
            status=Job.FAILED,
            compute_resource=self.job.compute_resource,
        )
        mock_update.return_value = True

        call_command("update_jobs_statuses")

        # Should only call for RUNNING_STATUSES jobs
        called_jobs = [call_args[0][0] for call_args in mock_update.call_args_list]
        for job in called_jobs:
            self.assertIn(job.status, Job.RUNNING_STATUSES)

    def test_command_help_text(self):
        """Test command has proper help text."""
        command = Command()
        self.assertEqual(command.help, "Update running job statuses and logs.")


class TestUpdateJobStatusEdgeCases(APITestCase):
    """Tests for edge cases in update_job_status function."""

    fixtures = ["tests/fixtures/schedule_fixtures.json"]

    def setUp(self):
        """Set up test fixtures."""
        self.job = Job.objects.get(id__exact="1a7947f9-6ae8-4e3d-ac1e-e7d608deec84")
        self.job.created = datetime.now()
        self.job.save()

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_all_ray_statuses(self, mock_get_handler):
        """Test all Ray job statuses are handled correctly."""
        ray_statuses = [
            (JobStatus.PENDING, Job.PENDING),
            (JobStatus.RUNNING, Job.RUNNING),
            (JobStatus.STOPPED, Job.STOPPED),
            (JobStatus.SUCCEEDED, Job.SUCCEEDED),
            (JobStatus.FAILED, Job.FAILED),
        ]

        for ray_status, expected_status in ray_statuses:
            mock_handler = MagicMock()
            mock_handler.status.return_value = ray_status
            mock_handler.logs.return_value = f"Logs for {ray_status}"
            mock_get_handler.return_value = mock_handler

            update_job_status(self.job)

            self.assertEqual(
                self.job.status,
                expected_status,
                f"Failed for {ray_status} -> {expected_status}",
            )

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_preserves_non_terminal_env_vars(self, mock_get_handler):
        """Test env_vars are preserved for non-terminal states."""
        self.job.env_vars = '{"token": "secret"}'
        self.job.sub_status = Job.MAPPING

        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = "Running"
        mock_get_handler.return_value = mock_handler

        update_job_status(self.job)

        self.assertEqual(self.job.status, Job.RUNNING)
        self.assertEqual(self.job.env_vars, '{"token": "secret"}')
        self.assertEqual(self.job.sub_status, Job.MAPPING)

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_empty_logs(self, mock_get_handler):
        """Test handling of empty logs."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = ""
        mock_get_handler.return_value = mock_handler

        update_job_status(self.job)

        self.assertEqual(self.job.logs, "")

    @patch("api.management.commands.update_jobs_statuses.get_job_handler")
    def test_update_job_status_none_logs(self, mock_get_handler):
        """Test handling of None logs - should initialize as empty string."""
        mock_handler = MagicMock()
        mock_handler.status.return_value = JobStatus.RUNNING
        mock_handler.logs.return_value = None
        mock_get_handler.return_value = mock_handler

        result = update_job_status(self.job)

        self.assertTrue(result)
        self.assertEqual(self.job.status, Job.RUNNING)
        self.assertEqual(self.job.logs, "")
