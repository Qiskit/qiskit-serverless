"""Tests to verify the cluster name generator."""

from core.services.runners.ray_runner import _generate_resource_name


def test_quantum_user_generation():
    """This test verifies the cluster name generation for IQP users."""
    username = "6bc1230a4g12340012345003"

    cluster_name = _generate_resource_name(username=username)
    assert not cluster_name.startswith("c-6bc1230a4g12340012345003-")
    assert cluster_name.startswith("c-6bc1230a4g1234001234")


def test_ibm_cloud_user_generation():
    """This test verifies the cluster name generation for IBM Cloud users."""
    username = "IBMid-123001ABCD"

    cluster_name = _generate_resource_name(username=username)
    assert cluster_name.startswith("c-ibmid-123001abcd-")


def test_weird_user_generation():
    """This test verifies the cluster name generation for a weird usern name."""
    username = "WE.IRD_?|-name"
    cluster_name = _generate_resource_name(username=username)
    assert cluster_name.startswith("c-we-ird----name-")
