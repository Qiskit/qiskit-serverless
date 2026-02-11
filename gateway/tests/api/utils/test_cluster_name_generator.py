"""Tests to verify the cluster name generator."""

from rest_framework.test import APITestCase

from core.utils import generate_cluster_name


class TestClusterNameGenerator(APITestCase):
    """Test suite to validate the cluster name generator."""

    def test_quantum_user_generation(self):
        """This test verifies the cluster name generation for IQP users."""
        username = "6bc1230a4g12340012345003"

        cluster_name = generate_cluster_name(username=username)
        self.assertFalse(cluster_name.startswith("c-6bc1230a4g12340012345003-"))
        self.assertTrue(cluster_name.startswith("c-6bc1230a4g1234001234"))

    def test_ibm_cloud_user_generation(self):
        """This test verifies the cluster name generation for IBM Cloud users."""
        username = "IBMid-123001ABCD"

        cluster_name = generate_cluster_name(username=username)
        self.assertTrue(cluster_name.startswith("c-ibmid-123001abcd-"))

    def test_weird_user_generation(self):
        """This test verifies the cluster name generation for a weird usern name."""
        username = "WE.IRD_?|-name"
        cluster_name = generate_cluster_name(username=username)
        self.assertTrue(cluster_name.startswith("c-we-ird----name-"))
