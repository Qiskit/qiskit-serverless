"""Tests for the Job admin: read-only status fields and the Stop job button."""

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from api.admin import JobAdmin
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program


class TestJobAdmin(APITestCase):

    def _post_change_form(self, job, program, user, overrides):
        """POST to the admin change form for job, starting from its current initial data."""
        url = reverse("admin:api_job_change", args=[job.pk])
        response_get = self.client.get(url)

        form = response_get.context["adminform"].form
        data = form.initial.copy()
        data = {k: v for k, v in data.items() if v is not None}
        signed_version = form["version"].value()

        data.update({"author": user.pk, "program": program.pk, "version": signed_version})
        data.update(overrides)

        return self.client.post(url, data, follow=True)

    def _post_stop(self, job, user):
        """POST to the dedicated Stop job endpoint, the same request the button's fetch sends."""
        self.client.login(username=user.username, password="pass")
        return self.client.post(reverse("admin:job_stop_job_view", args=[job.pk]))

    def test_job_status_sub_status_and_runner_are_not_editable(self):
        """status/sub_status/runner are read-only in the admin: posting new values changes nothing."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user)
        job = Job.objects.create(
            status=Job.PENDING, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        self._post_change_form(
            job,
            program,
            user,
            {"status": Job.RUNNING, "sub_status": Job.MAPPING, "runner": Program.FLEETS, "_save": "Save"},
        )

        job.refresh_from_db()
        assert job.status == Job.PENDING
        assert job.sub_status is None
        assert job.runner == Program.RAY
        assert JobEvent.objects.filter(job_id=job.id).count() == 0

    def test_status_is_rendered_as_the_same_badge_as_the_changelist(self):
        """The read-only status field in the edit page reuses status_badge, the same colored
        badge shown in the changelist, instead of a plain read-only text value."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.RAY)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        response = self.client.get(reverse("admin:api_job_change", args=[job.pk]))

        assert 'class="qs-status-badge" data-status="RUNNING"' in response.content.decode()

    def test_fleets_section_is_hidden_for_a_ray_job(self):
        """Only the Fleets/Ray fieldset matching the job's own runner is shown, not both."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.RAY)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        response = self.client.get(reverse("admin:api_job_change", args=[job.pk]))
        content = response.content.decode()

        assert "field-ray_job_id" in content
        assert "field-fleet_id" not in content

    def test_ray_section_is_hidden_for_a_fleets_job(self):
        """Only the Fleets/Ray fieldset matching the job's own runner is shown, not both."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.FLEETS)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.FLEETS
        )

        response = self.client.get(reverse("admin:api_job_change", args=[job.pk]))
        content = response.content.decode()

        assert "field-fleet_id" in content
        assert "field-ray_job_id" not in content

    def test_stop_job_button_stops_ray_job(self):
        """The Stop job button marks a non-terminal Ray job as STOPPED and logs a backoffice event."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.RAY)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        self._post_stop(job, user)

        job.refresh_from_db()
        assert job.status == Job.STOPPED

        job_events = JobEvent.objects.filter(job_id=job.id)
        assert job_events.count() == 1
        assert job_events[0].origin == JobEventOrigin.BACKOFFICE
        assert job_events[0].context == JobEventContext.STOP_JOB
        assert job_events[0].data["status"] == Job.STOPPED

    def test_stop_job_button_works_for_a_job_with_no_program(self):
        """A job whose program was deleted (program=None) can still be stopped: the dedicated
        endpoint never runs the Job change form, which would otherwise reject the missing
        required `program` field before the stop logic ever ran."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=None, runner=Program.RAY
        )

        self._post_stop(job, user)

        job.refresh_from_db()
        assert job.status == Job.STOPPED

    def test_stop_job_button_does_nothing_for_fleets_job(self):
        """The Stop job button is a Ray-only action: it must not touch a Fleets job."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.FLEETS)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.FLEETS
        )

        self._post_stop(job, user)

        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert JobEvent.objects.filter(job_id=job.id).count() == 0

    def test_stop_job_button_does_nothing_for_terminal_job(self):
        """A job already in a terminal state cannot be stopped again from the admin."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.RAY)
        job = Job.objects.create(
            status=Job.SUCCEEDED, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        self._post_stop(job, user)

        job.refresh_from_db()
        assert job.status == Job.SUCCEEDED
        assert JobEvent.objects.filter(job_id=job.id).count() == 0

    def test_stop_job_button_is_not_shown_on_the_add_page(self):
        """job_actions must key off obj._state.adding, not obj.pk: Job.id defaults to a fresh
        uuid the moment an (unsaved) instance is built, so pk is never None on the add page."""

        unsaved_job = Job(runner=Program.RAY, status=Job.QUEUED)

        assert unsaved_job.pk is not None
        assert unsaved_job._state.adding is True
        assert JobAdmin(Job, None).job_actions(unsaved_job) == "-"

    def test_stop_job_view_denies_a_staff_user_without_change_permission(self):
        """A staff user who lacks change permission on Job gets a 403: stop_job_view raises
        PermissionDenied, which Django's admin_view wrapper turns into a forbidden response."""

        user = User.objects.create_user(username="staff_no_perm", password="pass", is_staff=True)
        program = Program.objects.create(title=f"{user.username}-custom", author=user, runner=Program.RAY)
        job = Job.objects.create(
            status=Job.RUNNING, sub_status=None, author_id=user.pk, program=program, runner=Program.RAY
        )

        response = self._post_stop(job, user)

        assert response.status_code == 403
        job.refresh_from_db()
        assert job.status == Job.RUNNING
        assert JobEvent.objects.filter(job_id=job.id).count() == 0

    def test_delete_is_disabled_for_every_job(self):
        """Deleting a job would take its pending outbox row with it and lose the billing facts."""
        user = User.objects.create_user(username="author", password="pass")
        job = Job.objects.create(author=user, runner=Program.FLEETS, status=Job.QUEUED)

        assert JobAdmin(Job, None).has_delete_permission(request=None) is False
        assert JobAdmin(Job, None).has_delete_permission(request=None, obj=job) is False
