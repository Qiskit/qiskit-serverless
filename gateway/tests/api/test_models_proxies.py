"""Tests for proxies."""

from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.urls import reverse
from rest_framework.test import APITestCase
from unittest.mock import MagicMock, patch

from api.models import VIEW_PROGRAM_PERMISSION, Program
from api.models_proxies import QuantumUserProxy


class ProxiesTest(APITestCase):
    """Tests for proxies."""

    fixtures = ["tests/fixtures/acl_fixtures.json"]

    network_configuration = [
        {
            "name": "ibm-q",
            "groups": {
                "open": {
                    "name": "open",
                    "projects": {
                        "main": {
                            "name": "main",
                        }
                    },
                }
            },
        }
    ]

    network_configuration_without_project = [
        {
            "name": "ibm-q",
            "groups": {
                "open": {
                    "name": "open",
                }
            },
        }
    ]

    def test_query_to_view_test_user_programs(self):
        groups_id_for_view = [100, 101, 102, 103, 104]
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        # We give view permission to all groups
        for group_id_to_view in groups_id_for_view:
            group = Group.objects.get(pk=group_id_to_view)
            group.permissions.add(view_program_permission)

        # Call to program-list end-point
        test_user_proxy = QuantumUserProxy.objects.get(username="test_user")
        self.client.force_authenticate(user=test_user_proxy)
        response = self.client.get(reverse("v1:programs-list"), format="json")
        titles_from_response = []
        for program in response.data:
            titles_from_response.append(program["title"])

        programs_to_test = ["Public program", "Private program", "My program"]
        self.assertListEqual(titles_from_response, programs_to_test)

    def test_query_to_view_test_user_2_programs(self):
        groups_id_for_view = [100, 101, 102, 103, 104]
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        # We give view permission to all groups
        for group_id_to_view in groups_id_for_view:
            group = Group.objects.get(pk=group_id_to_view)
            group.permissions.add(view_program_permission)

        # Test user groups with view permissions
        test_user_2_proxy = QuantumUserProxy.objects.get(username="test_user_2")
        self.client.force_authenticate(user=test_user_2_proxy)
        response = self.client.get(reverse("v1:programs-list"), format="json")
        titles_from_response = []
        for program in response.data:
            titles_from_response.append(program["title"])

        programs_to_test = ["Public program"]
        self.assertListEqual(titles_from_response, programs_to_test)

    def test_query_to_run_test_user_programs(self):
        groups_id_for_run = [102, 104]
        run_program_permission = Permission.objects.get(codename="run_program")

        # We give run permission to specific groups
        for group_id_to_run in groups_id_for_run:
            group = Group.objects.get(pk=group_id_to_run)
            group.permissions.add(run_program_permission)

        program_with_run_permission = Program.objects.get(title="Private program")
        program_without_run_permission = Program.objects.get(title="Public program")

        test_user_proxy = QuantumUserProxy.objects.get(username="test_user")
        user_criteria = Q(user=test_user_proxy)
        run_permission_criteria = Q(permissions=run_program_permission)
        program_pk_criteria = Q(program_instances=program_with_run_permission)
        test_user_program_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria & program_pk_criteria
        )
        self.assertTrue(test_user_program_with_run_permissions.exists())

        program_pk_criteria = Q(program_instances=program_without_run_permission)
        test_user_program_without_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria & program_pk_criteria
        )
        self.assertFalse(test_user_program_without_run_permissions.exists())

    def test_instances_generation_from_quantum_network_with_projects(self):
        proxy = QuantumUserProxy()
        instances = proxy._get_instances_from_network(self.network_configuration)
        self.assertListEqual(instances, ["ibm-q", "ibm-q/open", "ibm-q/open/main"])

    def test_instances_generation_from_quantum_network_without_projects(self):
        proxy = QuantumUserProxy()
        instances = proxy._get_instances_from_network(
            self.network_configuration_without_project
        )
        self.assertListEqual(instances, ["ibm-q", "ibm-q/open"])

    @patch.object(QuantumUserProxy, "_get_network")
    def test_user_is_assigned_to_groups(self, get_network_mock: MagicMock):
        get_network_mock.return_value = self.network_configuration
        proxy = QuantumUserProxy.objects.get(username="test_user_3")
        proxy.update_groups("")

        groups_names = proxy.groups.values_list("name", flat=True).distinct()
        groups_names_list = list(groups_names)
        self.assertListEqual(
            groups_names_list, ["ibm-q", "ibm-q/open", "ibm-q/open/main"]
        )

        permissions = proxy.get_group_permissions()
        permissions_list = list(permissions)
        self.assertListEqual(permissions_list, ["api.view_program"])
