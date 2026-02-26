"""Tests for models."""

from django.contrib.auth.models import User, Group
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from api.context import impersonate

from core.models import Job, JobEvent, Program, ProgramHistory


class TestModels(APITestCase):
    """TestModels."""

    def test_job_is_terminal_state(self):
        """Tests job terminal state function."""
        job = Job()
        job.status = Job.PENDING
        self.assertFalse(job.in_terminal_state())

        job.status = Job.RUNNING
        self.assertFalse(job.in_terminal_state())

        job.status = Job.STOPPED
        self.assertTrue(job.in_terminal_state())

        job.status = Job.QUEUED
        self.assertFalse(job.in_terminal_state())

        job.status = Job.FAILED
        self.assertTrue(job.in_terminal_state())

        job.status = Job.SUCCEEDED
        self.assertTrue(job.in_terminal_state())


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

        self.assertEqual(ProgramHistory.objects.count(), 1)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=admin_user,
                field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                action=ProgramHistory.ADD,
                entity="Group",
                entity_id=str(group1.id),
                description="Group 1",
            )
        )

        with impersonate(admin_user):
            program.instances.add(group2)

        self.assertEqual(ProgramHistory.objects.count(), 2)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=admin_user,
                field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                action=ProgramHistory.ADD,
                entity="Group",
                entity_id=str(group2.id),
                description="Group 2",
            )
        )

        with impersonate(user):
            program.instances.remove(group1)

        self.assertEqual(ProgramHistory.objects.count(), 3)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=user,
                field_name=ProgramHistory.PROGRAM_FIELD_INSTANCES,
                action=ProgramHistory.REMOVE,
                entity="Group",
                entity_id=str(group1.id),
                description="Group 1",
            )
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

        self.assertEqual(ProgramHistory.objects.count(), 1)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=admin_user,
                field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                action=ProgramHistory.ADD,
                entity="Group",
                entity_id=str(group1.id),
                description="Group 1",
            )
        )

        with impersonate(admin_user):
            program.trial_instances.add(group2)

        self.assertEqual(ProgramHistory.objects.count(), 2)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=admin_user,
                field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                action=ProgramHistory.ADD,
                entity="Group",
                entity_id=str(group2.id),
                description="Group 2",
            )
        )

        with impersonate(user):
            program.trial_instances.remove(group1)

        self.assertEqual(ProgramHistory.objects.count(), 3)
        self.assertTrue(
            ProgramHistory.objects.get(
                program=program,
                user=user,
                field_name=ProgramHistory.PROGRAM_FIELD_TRIAL_INSTANCES,
                action=ProgramHistory.REMOVE,
                entity="Group",
                entity_id=str(group1.id),
                description="Group 1",
            )
        )


class TestJobAdmin(APITestCase):

    def test_job_status_change_creates_event(self):
        """This test simulates an admin access to the data base changing the status and sub status"""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(
            title=f"{user.username}-custom",
            author=user,
        )
        job = Job.objects.create(status=Job.PENDING, sub_status=None, author_id=user.pk, program=program)

        url = reverse("admin:api_job_change", args=[job.pk])
        response_get = self.client.get(url)

        form = response_get.context["adminform"].form
        data = form.initial.copy()

        data = {k: v for k, v in data.items() if v is not None}
        version_field = form["version"]
        signed_version = version_field.value()

        for inline_formset in response_get.context["inline_admin_formsets"]:
            management_form = inline_formset.formset.management_form
            for field_name in management_form.fields:
                data[f"{management_form.prefix}-{field_name}"] = management_form[field_name].value()

        data.update(
            {
                "status": Job.RUNNING,
                "sub_status": Job.MAPPING,
                "author": user.pk,
                "program": program.pk,
                "version": signed_version,
                "_save": "Save",
            }
        )

        self.client.post(url, data, follow=True)

        job_events = JobEvent.objects.filter(job_id=job.id)
        self.assertEqual(job_events.count(), 2)

        self.assertEquals(job_events[0].data["sub_status"], Job.MAPPING)
        self.assertEquals(job_events[1].data["status"], Job.RUNNING)

    def test_job_not_status_change_not_creates_event(self):
        """This test simulates an admin access to the data base changing the gpu value"""

        user = User.objects.create_superuser(username="admin", email="admin@test.com", password="pass")
        self.client.login(username="admin", password="pass")
        program = Program.objects.create(
            title=f"{user.username}-custom",
            author=user,
        )
        job = Job.objects.create(status=Job.PENDING, sub_status=None, author_id=user.pk, program=program)

        url = reverse("admin:api_job_change", args=[job.pk])
        response_get = self.client.get(url)

        form = response_get.context["adminform"].form
        data = form.initial.copy()

        data = {k: v for k, v in data.items() if v is not None}
        version_field = form["version"]
        signed_version = version_field.value()

        for inline_formset in response_get.context["inline_admin_formsets"]:
            management_form = inline_formset.formset.management_form
            for field_name in management_form.fields:
                data[f"{management_form.prefix}-{field_name}"] = management_form[field_name].value()

        data.update(
            {
                "gpu": True,
                "author": user.pk,
                "program": program.pk,
                "version": signed_version,
                "_save": "Save",
            }
        )

        self.client.post(url, data, follow=True)

        job_events = JobEvent.objects.filter(job_id=job.id)
        self.assertEqual(job_events.count(), 0)
