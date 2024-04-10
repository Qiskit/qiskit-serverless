"""Tests for proxies."""

from rest_framework.test import APITestCase
from unittest.mock import patch

from api.models_proxies import QuantumUserProxy


class ProxiesTest(APITestCase):
    """Tests for proxies."""

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

    @patch("api.models_proxies.QuantumUserProxy.get_network")
    def test_instances_from_network_configuration(self, mockQuantumUserProxy):
        mockQuantumUserProxy.return_value = self.network_configuration
        proxy = QuantumUserProxy()
        instances = proxy.get_instances_from_network("")
        self.assertListEqual(instances, ["ibm-q/open/main"])

    @patch("api.models_proxies.QuantumUserProxy.get_network")
    def test_instances_from_network_configuratio_without_project(
        self, mockQuantumUserProxy
    ):
        mockQuantumUserProxy.return_value = self.network_configuration_without_project
        proxy = QuantumUserProxy()
        instances = proxy.get_instances_from_network("")
        self.assertListEqual(instances, ["ibm-q/open"])
