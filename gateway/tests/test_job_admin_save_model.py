"""Tests for JobAdmin.save_model ordering and delete permission."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User

from api.admin import JobAdmin
from core.models import Job, Program

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class TestSaveModelOrdering:
    def test_persists_the_job_before_creating_the_status_event(self, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)
        job.status = Job.STOPPED
        form = MagicMock()
        form.changed_data = ["status"]

        call_order = []
        original_save = Job.save

        def spy_save(self, *args, **kwargs):
            call_order.append("job_saved")
            return original_save(self, *args, **kwargs)

        with patch("api.admin.JobEvent") as mock_job_event:
            mock_job_event.objects.add_status_event.side_effect = lambda **kw: call_order.append("event_created")
            with patch.object(Job, "save", spy_save):
                JobAdmin(Job, None).save_model(request=None, obj=job, form=form, change=True)

        assert call_order == ["job_saved", "event_created"]

    def test_does_nothing_extra_when_status_unchanged(self, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)
        form = MagicMock()
        form.changed_data = []

        with patch("api.admin.JobEvent") as mock_job_event:
            JobAdmin(Job, None).save_model(request=None, obj=job, form=form, change=True)

        mock_job_event.objects.add_status_event.assert_not_called()


class TestDeletePermission:
    def test_delete_permission_is_always_false(self, user):
        job = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)

        assert JobAdmin(Job, None).has_delete_permission(request=None) is False
        assert JobAdmin(Job, None).has_delete_permission(request=None, obj=job) is False
