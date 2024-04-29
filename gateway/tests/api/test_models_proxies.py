"""Tests for proxies."""

from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from rest_framework.test import APITestCase
from unittest.mock import MagicMock, patch

from api.models import Program
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
        view_program_permission = Permission.objects.get(codename="view_program")

        # We give view permission to all groups
        for group_id_to_view in groups_id_for_view:
            group = Group.objects.get(pk=group_id_to_view)
            group.permissions.add(view_program_permission)

        # Test user groups with view permissions
        test_user_proxy = QuantumUserProxy.objects.get(username="test_user")
        user_criteria = Q(user=test_user_proxy)
        view_permission_criteria = Q(permissions=view_program_permission)
        test_user_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )
        groups_pks_list = list(
            test_user_groups_with_view_permissions.values_list("pk", flat=True)
        )
        groups_to_test = [100, 101, 103, 104]
        self.assertListEqual(groups_pks_list, groups_to_test)

        # List programs that user has access
        author_criteria = Q(author=test_user_proxy)
        test_user_groups_with_view_permissions_criteria = Q(
            instances__in=test_user_groups_with_view_permissions
        )
        test_user_programs_with_access = Program.objects.filter(
            author_criteria | test_user_groups_with_view_permissions_criteria
        ).distinct()
        programs_title_list = list(
            test_user_programs_with_access.values_list("title", flat=True)
        )
        programs_to_test = ["My program", "Private program", "Public program"]
        self.assertListEqual(programs_title_list, programs_to_test)

    def test_query_to_view_test_user_2_programs(self):
        groups_id_for_view = [100, 101, 102, 103, 104]
        view_program_permission = Permission.objects.get(codename="view_program")

        # We give view permission to all groups
        for group_id_to_view in groups_id_for_view:
            group = Group.objects.get(pk=group_id_to_view)
            group.permissions.add(view_program_permission)

        # Test user groups with view permissions
        test_user_proxy = QuantumUserProxy.objects.get(username="test_user_2")
        user_criteria = Q(user=test_user_proxy)
        view_permission_criteria = Q(permissions=view_program_permission)
        test_user_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )
        groups_pks_list = list(
            test_user_groups_with_view_permissions.values_list("pk", flat=True)
        )
        groups_to_test = [100, 101, 102]
        self.assertListEqual(groups_pks_list, groups_to_test)

        # List programs that user has access
        author_criteria = Q(author=test_user_proxy)
        test_user_groups_with_view_permissions_criteria = Q(
            instances__in=test_user_groups_with_view_permissions
        )
        test_user_programs_with_access = Program.objects.filter(
            author_criteria | test_user_groups_with_view_permissions_criteria
        ).distinct()
        programs_title_list = list(
            test_user_programs_with_access.values_list("title", flat=True)
        )
        programs_to_test = ["Public program"]
        self.assertListEqual(programs_title_list, programs_to_test)

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
        program_pk_criteria = Q(program=program_with_run_permission)
        test_user_program_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria & program_pk_criteria
        )
        self.assertTrue(test_user_program_with_run_permissions.exists())

        program_pk_criteria = Q(program=program_without_run_permission)
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
