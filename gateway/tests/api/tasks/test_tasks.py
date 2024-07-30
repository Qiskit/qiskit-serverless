from django.contrib.auth import models
from rest_framework.test import APITestCase, override_settings
from rest_framework import status

from api.models import RUN_PROGRAM_PERMISSION, Provider, Program
from api.tasks import programs, providers


class TestProgramApi(APITestCase):
    """TestProgramApi."""

    fixtures = ["tests/fixtures/tasks_fixtures.json"]

    @override_settings(
        PROVIDERS_CONFIGURATION='{"test_provider": {"admin_group": "runner", "registry": "docker.io/"}}'
    )
    def test_assign_admin_group(self):
        """This test will check assign admin group task"""

        providers.assign_admin_group()

        provider = Provider.objects.get(name="test_provider")
        self.assertEqual(provider.admin_group.name, "runner")

    @override_settings(
        PROVIDERS_CONFIGURATION='{"test_provider": {"admin_group": "runner", "registry": "docker.io/"}}'
    )
    @override_settings(
        FUNCTIONS_PERMISSIONS='{"function_provider": {"provider": "test_provider", "instances": ["runner", "manager"]}}'
    )
    def test_assign_run_permission(self):
        providers.assign_admin_group()

        user = models.User.objects.get(username="test_user")
        self.client.force_authenticate(user=user)

        programs_response = self.client.post(
            "/api/v1/programs/upload/",
            data={
                "title": "function_provider",
                "dependencies": "[]",
                "env_vars": "{}",
                "image": "docker.io/awesome-namespace/awesome-title",
                "provider": "test_provider",
            },
        )
        self.assertEqual(programs_response.status_code, status.HTTP_200_OK)

        programs.assign_run_permission()

        program = Program.objects.get(title="function_provider")
        self.assertEqual(len(program.instances.all()), 2)
        self.assertEqual(program.instances.all()[0].name, "runner")
        self.assertEqual(program.instances.all()[1].name, "manager")

        run_permission = models.Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)
        runner_group = program.instances.all()[0]
        self.assertEqual(len(runner_group.permissions.all()), 2)
        self.assertTrue(runner_group.permissions.filter(id=run_permission.pk).exists())

        manager_group = program.instances.all()[1]
        self.assertEqual(len(manager_group.permissions.all()), 2)
        self.assertTrue(manager_group.permissions.filter(id=run_permission.pk).exists())
