"""Tests for models."""

from django.contrib.auth.models import User, Group
from django.test import TransactionTestCase
from rest_framework.test import APITestCase
from api.context import impersonate

from api.models import Job, Program, ProgramHistory


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
    def test_program_instances_signal(self):
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
