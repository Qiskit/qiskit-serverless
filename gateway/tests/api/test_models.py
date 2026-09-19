"""Tests for models."""

from django.contrib.auth.models import User, Group
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from api.context import impersonate

from api.admin import JobAdmin
from core.model_managers.job_events import JobEventContext, JobEventOrigin
from core.models import Job, JobEvent, Program, ProgramHistory


class TestModels(APITestCase):
    """TestModels."""

    def test_job_is_terminal_state(self):
        """Tests job terminal state function."""
        job = Job()
        job.status = Job.PENDING
        assert not job.in_terminal_state()

        job.status = Job.RUNNING
        assert not job.in_terminal_state()

        job.status = Job.STOPPED
        assert job.in_terminal_state()

        job.status = Job.QUEUED
        assert not job.in_terminal_state()

        job.status = Job.FAILED
        assert job.in_terminal_state()

        job.status = Job.SUCCEEDED
        assert job.in_terminal_state()


class TestProgramSignals(TransactionTestCase):
    """Test signals in Program model."""

    def test_program_instances_signal(self):
        """Tests post_add and post_remove signal in program model when instance field is updated."""
        user = User.objects.create_user(username="test_user")
        admin_user = User.objects.create_user(username="admin_user", is_staff=True)
        program = Program.objects.create(title="Title", author=user)
        group1 = Group.objects.create(name="Group 1")
        group2 = Group.objects.create(name="Group 2")

        with impersonate(admin_user):
            program.instances.add(group1)

        assert ProgramHistory.objects.count() == 1
        assert ProgramHistory.objects.get(
            program=program,
            user=admin_user,
            field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
            action=ProgramHistory.ADD,
            entity="Group",
            entity_id=str(group1.id),
            description="Group 1",
        )

        with impersonate(admin_user):
            program.instances.add(group2)

        assert ProgramHistory.objects.count() == 2
        assert ProgramHistory.objects.get(
            program=program,
            user=admin_user,
            field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
            action=ProgramHistory.ADD,
            entity="Group",
            entity_id=str(group2.id),
            description="Group 2",
        )

        with impersonate(user):
            program.instances.remove(group1)

        assert ProgramHistory.objects.count() == 3
        assert ProgramHistory.objects.get(
            program=program,
            user=user,
            field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
            action=ProgramHistory.REMOVE,
            entity="Group",
            entity_id=str(group1.id),
            description="Group 1",
        )

    def test_program_trial_instances_signal(self):
        """Tests post_add and post_remove signal in program model when trial_instance
        field is updated."""
        user = User.objects.create_user(username="test_user")
        admin_user = User.objects.create_user(username="admin_user2", is_staff=True)
        program = Program.objects.create(title="Title", author=user)
        group1 = Group.objects.create(name="Group 1")
        group2 = Group.objects.create(name="Group 2")

        with impersonate(admin_user):
            program.trial_instances.add(group1)

        assert ProgramHistory.objects.count() == 1
        assert ProgramHistory.objects.get(
            program=program,
            user=admin_user,
            field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
            action=ProgramHistory.ADD,
            entity="Group",
            entity_id=str(group1.id),
            description="Group 1",
        )

        with impersonate(admin_user):
            program.trial_instances.add(group2)

        assert ProgramHistory.objects.count() == 2
        assert ProgramHistory.objects.get(
            program=program,
            user=admin_user,
            field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
            action=ProgramHistory.ADD,
            entity="Group",
            entity_id=str(group2.id),
            description="Group 2",
        )

        with impersonate(user):
            program.trial_instances.remove(group1)

        assert ProgramHistory.objects.count() == 3
        assert ProgramHistory.objects.get(
            program=program,
            user=user,
            field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
            action=ProgramHistory.REMOVE,
            entity="Group",
            entity_id=str(group1.id),
            description="Group 1",
        )


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

    def test_job_status_and_sub_status_are_not_editable(self):
        """status/sub_status are read-only in the admin: posting new values changes nothing."""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(title=f"{user.username}-custom", author=user)
        job = Job.objects.create(status=Job.PENDING, sub_status=None, author_id=user.pk, program=program)

        self._post_change_form(
            job,
            program,
            user,
            {"status": Job.RUNNING, "sub_status": Job.MAPPING, "_save": "Save"},
        )

        job.refresh_from_db()
        assert job.status == Job.PENDING
        assert job.sub_status is None
        assert JobEvent.objects.filter(job_id=job.id).count() == 0

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
