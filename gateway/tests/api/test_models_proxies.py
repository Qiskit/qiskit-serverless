"""Tests for proxies."""

from rest_framework.test import APITestCase
from unittest.mock import MagicMock, patch

from api.models_proxies import QuantumUserProxy


class ProxiesTest(APITestCase):
    """Tests for proxies."""

    fixtures = ["tests/fixtures/fixtures.json"]

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

    def test_instances_generation_from_quantum_network_with_projects(self):
        proxy = QuantumUserProxy()
        instances = proxy._get_instances_from_network(self.network_configuration)
        self.assertListEqual(instances, ["ibm-q", "ibm-q/open", "ibm-q/open/main"])

    def test_instances_generation_from_quantum_network_without_projects(self):
        proxy = QuantumUserProxy()
        instances = proxy._get_instances_from_network(self.network_configuration_without_project)
        self.assertListEqual(instances, ["ibm-q", "ibm-q/open"])

    @patch.object(QuantumUserProxy, "_get_network")
    def test_user_is_assigned_to_groups(self, get_network_mock: MagicMock):
        get_network_mock.return_value = self.network_configuration
        proxy = QuantumUserProxy.objects.get(username="test_user")
        proxy.update_groups("")

        groups_names = proxy.groups.values_list("name", flat=True).distinct()
        groups_names_list = list(groups_names)
        self.assertListEqual(groups_names_list, ["ibm-q", "ibm-q/open", "ibm-q/open/main"])

