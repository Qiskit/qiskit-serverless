# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for QuantumServerless."""
import json
from unittest import TestCase

import ray
import requests_mock

from quantum_serverless import QuantumServerless, Provider
from quantum_serverless.core import Cluster
from quantum_serverless.quantum_serverless import get_auto_discovered_provider


class TestQuantumServerless(TestCase):
    """Tests for QuantumServerless."""

    def test_qs_class(self):
        """Tests template class."""
        serverless = QuantumServerless()

        with serverless.context():
            self.assertTrue(ray.is_initialized())

        self.assertFalse(ray.is_initialized())

    def test_for_at_least_one_cluster_and_one_provider(self):
        """Test for at least one cluster."""
        serverless = QuantumServerless()

        self.assertEqual(len(serverless.clusters()), 1)
        self.assertEqual(len(serverless.providers()), 1)

    def test_add_provider(self):
        """Test addition of provider."""
        serverless = QuantumServerless()
        self.assertEqual(len(serverless.providers()), 1)

        serverless.add_provider(Provider("my_provider"))
        self.assertEqual(len(serverless.providers()), 2)

    def test_add_cluster(self):
        """Tests add cluster method."""
        serverless = QuantumServerless()

        self.assertEqual(len(serverless.clusters()), 1)

        serverless.add_cluster(Cluster(name="New local cluster"))
        self.assertEqual(len(serverless.clusters()), 2)

        self.assertIsInstance(serverless.set_cluster(1), QuantumServerless)

    def test_all_context_allocations(self):
        """Test context allocation from provider and cluster calls."""
        serverless = QuantumServerless()

        with serverless:
            self.assertTrue(ray.is_initialized())
        self.assertFalse(ray.is_initialized())

        with serverless.provider("local"):
            self.assertTrue(ray.is_initialized())
        self.assertFalse(ray.is_initialized())

        with serverless.cluster("local"):
            self.assertTrue(ray.is_initialized())
        self.assertFalse(ray.is_initialized())

        with serverless.cluster(Cluster("local")):
            self.assertTrue(ray.is_initialized())
        self.assertFalse(ray.is_initialized())

    def test_load_config(self):
        """Tests configuration loading."""
        config = {"providers": [{"name": "local2", "cluster": {"name": "local2"}}]}

        serverless = QuantumServerless(config)
        self.assertEqual(len(serverless.providers()), 2)

    def test_available_clusters_with_mock(self):
        """Test for external api call for available clusters."""
        manager_address = "http://mock_host:42"

        with requests_mock.Mocker() as mocker:
            clusters_mocks = [{"name": f"mock-cluster-{i}"} for i in range(4)]
            mocker.get(
                "http://mock_host:42/quantum-serverless-manager/cluster/",
                text=json.dumps(clusters_mocks),
            )
            for mock_cluster in clusters_mocks:
                name = mock_cluster.get("name")
                mocker.get(
                    f"http://mock_host:42/quantum-serverless-manager/cluster/{name}",
                    text=json.dumps(
                        {
                            "name": name,
                            "host": f"{name}_host",
                            "port": 42,
                            "ip_address": "127.0.0.1",
                        }
                    ),
                )
            serverless = QuantumServerless()
            providers = serverless.providers()

            self.assertEqual(len(providers), 1)
            for provider in providers:
                self.assertIsInstance(provider, Provider)

            provider = get_auto_discovered_provider(manager_address, token="token")

            self.assertIsInstance(provider, Provider)

            if isinstance(provider, Provider):
                self.assertIsInstance(provider.cluster, Cluster)
                self.assertEqual(len(provider.available_clusters), 4)
                for cluster in provider.available_clusters:
                    self.assertIsInstance(cluster, Cluster)
