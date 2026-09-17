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
