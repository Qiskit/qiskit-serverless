"""Tests for models."""

from django.contrib.auth.models import User, Group
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from api.context import impersonate

from core.models import Job, JobEvent, Program, ProgramHistory, CodeEngineProject, ComputeResource


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


class TestCodeEngineProject(APITestCase):
    """Tests for CodeEngineProject model."""

    def test_code_engine_project_creation(self):
        """Tests creating a CodeEngineProject with all required fields."""
        project = CodeEngineProject.objects.create(
            project_id="ce-project-123-456",
            project_name="test-project",
            region="us-east",
            resource_group_id="rg-123456",
            subnet_pool_id="subnet-pool-789",
            pds_name_state="pds-state-store",
            pds_name_users="pds-users-store",
            pds_name_providers="pds-providers-store",
            active=True,
        )

        self.assertIsNotNone(project.id)
        self.assertEqual(project.project_id, "ce-project-123-456")
        self.assertEqual(project.project_name, "test-project")
        self.assertEqual(project.region, "us-east")
        self.assertEqual(project.resource_group_id, "rg-123456")
        self.assertEqual(project.subnet_pool_id, "subnet-pool-789")
        self.assertEqual(project.pds_name_state, "pds-state-store")
        self.assertEqual(project.pds_name_users, "pds-users-store")
        self.assertEqual(project.pds_name_providers, "pds-providers-store")
        self.assertTrue(project.active)
        self.assertIsNotNone(project.created)
        self.assertIsNotNone(project.updated)

    def test_code_engine_project_default_active(self):
        """Tests that active field defaults to True."""
        project = CodeEngineProject.objects.create(
            project_id="ce-project-default",
            project_name="default-project",
            region="eu-de",
            resource_group_id="rg-default",
            subnet_pool_id="subnet-default",
            pds_name_state="pds-state",
            pds_name_users="pds-users",
            pds_name_providers="pds-providers",
        )

        self.assertTrue(project.active)

    def test_code_engine_project_unique_project_id(self):
        """Tests that project_id must be unique."""
        CodeEngineProject.objects.create(
            project_id="ce-unique-123",
            project_name="project-1",
            region="us-south",
            resource_group_id="rg-1",
            subnet_pool_id="subnet-1",
            pds_name_state="pds-state-1",
            pds_name_users="pds-users-1",
            pds_name_providers="pds-providers-1",
        )

        # Attempting to create another project with the same project_id should fail
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            CodeEngineProject.objects.create(
                project_id="ce-unique-123",  # Duplicate project_id
                project_name="project-2",
                region="us-east",
                resource_group_id="rg-2",
                subnet_pool_id="subnet-2",
                pds_name_state="pds-state-2",
                pds_name_users="pds-users-2",
                pds_name_providers="pds-providers-2",
            )

    def test_code_engine_project_str_representation(self):
        """Tests the string representation of CodeEngineProject."""
        project = CodeEngineProject.objects.create(
            project_id="ce-str-test",
            project_name="my-test-project",
            region="eu-gb",
            resource_group_id="rg-str",
            subnet_pool_id="subnet-str",
            pds_name_state="pds-state-str",
            pds_name_users="pds-users-str",
            pds_name_providers="pds-providers-str",
        )

        self.assertEqual(str(project), "my-test-project (eu-gb)")

    def test_code_engine_project_update_timestamp(self):
        """Tests that updated timestamp changes on save."""
        project = CodeEngineProject.objects.create(
            project_id="ce-update-test",
            project_name="update-project",
            region="us-east",
            resource_group_id="rg-update",
            subnet_pool_id="subnet-update",
            pds_name_state="pds-state-update",
            pds_name_users="pds-users-update",
            pds_name_providers="pds-providers-update",
        )

        original_updated = project.updated

        # Update a field and save
        project.active = False
        project.save()

        # Refresh from database
        project.refresh_from_db()

        self.assertNotEqual(project.updated, original_updated)
        self.assertFalse(project.active)

    def test_code_engine_project_inactive_status(self):
        """Tests setting a project as inactive."""
        project = CodeEngineProject.objects.create(
            project_id="ce-inactive-test",
            project_name="inactive-project",
            region="jp-tok",
            resource_group_id="rg-inactive",
            subnet_pool_id="subnet-inactive",
            pds_name_state="pds-state-inactive",
            pds_name_users="pds-users-inactive",
            pds_name_providers="pds-providers-inactive",
            active=False,
        )

        self.assertFalse(project.active)

    def test_code_engine_project_query_active(self):
        """Tests querying for active projects."""
        # Create active project
        CodeEngineProject.objects.create(
            project_id="ce-active-1",
            project_name="active-project-1",
            region="us-east",
            resource_group_id="rg-active-1",
            subnet_pool_id="subnet-active-1",
            pds_name_state="pds-state-active-1",
            pds_name_users="pds-users-active-1",
            pds_name_providers="pds-providers-active-1",
            active=True,
        )

        # Create inactive project
        CodeEngineProject.objects.create(
            project_id="ce-inactive-1",
            project_name="inactive-project-1",
            region="us-east",
            resource_group_id="rg-inactive-1",
            subnet_pool_id="subnet-inactive-1",
            pds_name_state="pds-state-inactive-1",
            pds_name_users="pds-users-inactive-1",
            pds_name_providers="pds-providers-inactive-1",
            active=False,
        )

        active_projects = CodeEngineProject.objects.filter(active=True)
        self.assertEqual(active_projects.count(), 1)
        self.assertEqual(active_projects.first().project_id, "ce-active-1")

    def test_code_engine_project_query_by_region(self):
        """Tests querying projects by region."""
        CodeEngineProject.objects.create(
            project_id="ce-us-east-1",
            project_name="us-project",
            region="us-east",
            resource_group_id="rg-us",
            subnet_pool_id="subnet-us",
            pds_name_state="pds-state-us",
            pds_name_users="pds-users-us",
            pds_name_providers="pds-providers-us",
        )

        CodeEngineProject.objects.create(
            project_id="ce-eu-de-1",
            project_name="eu-project",
            region="eu-de",
            resource_group_id="rg-eu",
            subnet_pool_id="subnet-eu",
            pds_name_state="pds-state-eu",
            pds_name_users="pds-users-eu",
            pds_name_providers="pds-providers-eu",
        )

        us_projects = CodeEngineProject.objects.filter(region="us-east")
        self.assertEqual(us_projects.count(), 1)
        self.assertEqual(us_projects.first().project_name, "us-project")

    def test_code_engine_project_all_pds_fields(self):
        """Tests that all three PDS fields are properly stored."""
        project = CodeEngineProject.objects.create(
            project_id="ce-pds-test",
            project_name="pds-project",
            region="us-south",
            resource_group_id="rg-pds",
            subnet_pool_id="subnet-pds",
            pds_name_state="state-pds-name",
            pds_name_users="users-pds-name",
            pds_name_providers="providers-pds-name",
        )

        # Verify all three PDS fields are distinct and properly stored
        self.assertEqual(project.pds_name_state, "state-pds-name")
        self.assertEqual(project.pds_name_users, "users-pds-name")
        self.assertEqual(project.pds_name_providers, "providers-pds-name")
        self.assertNotEqual(project.pds_name_state, project.pds_name_users)
        self.assertNotEqual(project.pds_name_users, project.pds_name_providers)


class TestJobCodeEngineFields(APITestCase):
    """Tests for Job model Code Engine related fields."""

    def test_job_with_code_engine_project(self):
        """Tests creating a Job with a Code Engine project."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        ce_project = CodeEngineProject.objects.create(
            project_id="ce-test-123",
            project_name="test-project",
            region="us-east",
            resource_group_id="rg-123",
            subnet_pool_id="subnet-123",
            pds_name_state="pds-state",
            pds_name_users="pds-users",
            pds_name_providers="pds-providers",
        )

        job = Job.objects.create(
            author=user,
            program=program,
            code_engine_project=ce_project,
            fleet_id="fleet-abc-123",
        )

        self.assertIsNotNone(job.code_engine_project)
        self.assertEqual(job.code_engine_project.project_id, "ce-test-123")
        self.assertEqual(job.fleet_id, "fleet-abc-123")
        self.assertIsNone(job.compute_resource)
        self.assertIsNone(job.ray_job_id)

    def test_job_with_ray_compute_resource(self):
        """Tests creating a Job with Ray compute resource (existing behavior)."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        compute_resource = ComputeResource.objects.create(
            title="test-ray-cluster",
            host="ray://localhost:10001",
        )

        job = Job.objects.create(
            author=user,
            program=program,
            compute_resource=compute_resource,
            ray_job_id="ray-job-456",
        )

        self.assertIsNotNone(job.compute_resource)
        self.assertEqual(job.compute_resource.title, "test-ray-cluster")
        self.assertEqual(job.ray_job_id, "ray-job-456")
        self.assertIsNone(job.code_engine_project)
        self.assertIsNone(job.fleet_id)

    def test_job_without_runner_resources(self):
        """Tests creating a Job without any runner resources (queued state)."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        job = Job.objects.create(
            author=user,
            program=program,
            status=Job.QUEUED,
        )

        self.assertIsNone(job.compute_resource)
        self.assertIsNone(job.code_engine_project)
        self.assertIsNone(job.ray_job_id)
        self.assertIsNone(job.fleet_id)
        self.assertEqual(job.status, Job.QUEUED)

    def test_job_code_engine_project_cascade_on_delete(self):
        """Tests that Job.code_engine_project is set to NULL when CodeEngineProject is deleted."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        ce_project = CodeEngineProject.objects.create(
            project_id="ce-cascade-test",
            project_name="cascade-project",
            region="us-south",
            resource_group_id="rg-cascade",
            subnet_pool_id="subnet-cascade",
            pds_name_state="pds-state-cascade",
            pds_name_users="pds-users-cascade",
            pds_name_providers="pds-providers-cascade",
        )

        job = Job.objects.create(
            author=user,
            program=program,
            code_engine_project=ce_project,
            fleet_id="fleet-cascade-123",
        )

        # Delete the Code Engine project
        ce_project.delete()

        # Refresh job from database
        job.refresh_from_db()

        # Job should still exist but code_engine_project should be NULL
        self.assertIsNone(job.code_engine_project)
        self.assertEqual(job.fleet_id, "fleet-cascade-123")  # fleet_id remains

    def test_job_fleet_id_optional(self):
        """Tests that fleet_id is optional even when code_engine_project is set."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        ce_project = CodeEngineProject.objects.create(
            project_id="ce-optional-fleet",
            project_name="optional-fleet-project",
            region="eu-de",
            resource_group_id="rg-optional",
            subnet_pool_id="subnet-optional",
            pds_name_state="pds-state-optional",
            pds_name_users="pds-users-optional",
            pds_name_providers="pds-providers-optional",
        )

        job = Job.objects.create(
            author=user,
            program=program,
            code_engine_project=ce_project,
            # fleet_id not provided
        )

        self.assertIsNotNone(job.code_engine_project)
        self.assertIsNone(job.fleet_id)

    def test_job_query_by_code_engine_project(self):
        """Tests querying jobs by Code Engine project."""
        user = User.objects.create_user(username="test_user")
        program = Program.objects.create(title="Test Program", author=user)

        ce_project1 = CodeEngineProject.objects.create(
            project_id="ce-query-1",
            project_name="query-project-1",
            region="us-east",
            resource_group_id="rg-query-1",
            subnet_pool_id="subnet-query-1",
            pds_name_state="pds-state-1",
            pds_name_users="pds-users-1",
            pds_name_providers="pds-providers-1",
        )

        ce_project2 = CodeEngineProject.objects.create(
            project_id="ce-query-2",
            project_name="query-project-2",
            region="eu-de",
            resource_group_id="rg-query-2",
            subnet_pool_id="subnet-query-2",
            pds_name_state="pds-state-2",
            pds_name_users="pds-users-2",
            pds_name_providers="pds-providers-2",
        )

        # Create jobs with different projects
        Job.objects.create(author=user, program=program, code_engine_project=ce_project1)
        Job.objects.create(author=user, program=program, code_engine_project=ce_project1)
        Job.objects.create(author=user, program=program, code_engine_project=ce_project2)

        # Query jobs by project
        jobs_project1 = Job.objects.filter(code_engine_project=ce_project1)
        jobs_project2 = Job.objects.filter(code_engine_project=ce_project2)

        self.assertEqual(jobs_project1.count(), 2)
        self.assertEqual(jobs_project2.count(), 1)
