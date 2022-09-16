"""Tests for QuantumServerless."""
import json
import os
from unittest import TestCase, mock

import ray
import requests_mock

from quantum_serverless import QuantumServerless
from quantum_serverless.core.cluster import Cluster
from quantum_serverless.core.quantum_serverless import get_clusters
from quantum_serverless.exception import QuantumServerlessException


class TestQuantumServerless(TestCase):
    """Tests for QuantumServerless."""

    def test_qs_class(self):
        """Tests template class."""
        serverless = QuantumServerless()

        with serverless.context():
            self.assertTrue(ray.is_initialized())

        self.assertFalse(ray.is_initialized())

    def test_for_at_least_one_cluster(self):
        """Test for at least one cluster."""
        serverless = QuantumServerless()

        self.assertEqual(len(serverless.clusters()), 1)

    @mock.patch.dict(
        os.environ,
        {"QS_TOKEN": "<TOKEN>", "QS_CLUSTER_MANAGER_ADDRESS": "http://mock_host:42"},
    )
    def test_env_auth_details(self):
        """Test for env var auth / cluster details."""

        with requests_mock.Mocker() as mocker:
            clusters_mocks = [{"name": f"mock-cluster-{i}"} for i in range(4)]
            mocker.get(
                "http://mock_host:42/quantum-serverless-middleware/cluster/",
                text=json.dumps(clusters_mocks),
            )
            for mock_cluster in clusters_mocks:
                name = mock_cluster.get("name")
                mocker.get(
                    f"http://mock_host:42/quantum-serverless-middleware/cluster/{name}",
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
            clusters = serverless.clusters()

            self.assertEqual(len(clusters), 5)
            for cluster in clusters:
                self.assertIsInstance(cluster, Cluster)

    def test_available_clusters_with_mock(self):
        """Test for external api call for available clusters."""
        manager_address = "http://mock_host:42"

        with requests_mock.Mocker() as mocker:
            clusters_mocks = [{"name": f"mock-cluster-{i}"} for i in range(4)]
            mocker.get(
                "http://mock_host:42/quantum-serverless-middleware/cluster/",
                text=json.dumps(clusters_mocks),
            )
            for mock_cluster in clusters_mocks:
                name = mock_cluster.get("name")
                mocker.get(
                    f"http://mock_host:42/quantum-serverless-middleware/cluster/{name}",
                    text=json.dumps(
                        {
                            "name": name,
                            "host": f"{name}_host",
                            "port": 42,
                            "ip_address": "127.0.0.1",
                        }
                    ),
                )
            serverless = QuantumServerless(manager_address=manager_address)
            clusters = serverless.clusters()

            self.assertEqual(len(clusters), 5)
            for cluster in clusters:
                self.assertIsInstance(cluster, Cluster)

            clusters_from_function = get_clusters(manager_address, token="token")

            self.assertEqual(len(clusters_from_function), 4)
            for cluster in clusters_from_function:
                self.assertIsInstance(cluster, Cluster)

    def test_add_cluster(self):
        """Tests add cluster method."""
        serverless = QuantumServerless()

        self.assertEqual(len(serverless.clusters()), 1)

        serverless.add_cluster(Cluster(name="New local cluster", is_local=True))
        self.assertEqual(len(serverless.clusters()), 2)

        self.assertIsInstance(serverless.set_cluster(1), QuantumServerless)

    def test_cluster_class(self):
        """Test cluster class."""
        cluster = Cluster("ibm")
        self.assertFalse(cluster.is_local)

        with self.assertRaises(QuantumServerlessException):
            cluster.connection_string_job_server()
