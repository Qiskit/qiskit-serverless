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

"""Tests for ClusterDAO """
from unittest.mock import MagicMock
from unittest import TestCase
import unittest
from manager.cluster_dao import ClusterDAO
from manager.errors import CommandError, NotFoundError


def error_cluster_exists(*args):
    """Mock for command error."""
    raise CommandError(
        "Error: INSTALLATION FAILED: cannot re-use a name that is still in use"
    )


def error_cluster_not_found(*args):
    """Mock for cluster not found as returned by command."""
    raise CommandError('Error from server (NotFound): services "XXX" not found')


class TestClusterDao(TestCase):
    """Tests for Cluster DAO."""

    def test_get_all_data_valid(self):
        """Test successful get all data"""
        cluster_dao = ClusterDAO("ray")
        cluster_dao.run = MagicMock()
        cluster_dao.run.return_value = "example-cluster-4\nmy-cluster\nother-cluster"

        result = cluster_dao.get_all()

        assert len(result) == 3
        assert result[0]["name"] == "example-cluster-4"
        assert result[1]["name"] == "my-cluster"
        assert result[2]["name"] == "other-cluster"

    def test_get_data_formatted(self):
        """Test successful get cluster details"""
        cluster_dao = ClusterDAO("ray")
        cluster_dao.run = MagicMock()
        cluster_dao.run.return_value = "10.102.15.119"

        result = cluster_dao.get("cluster")

        assert result["name"] == "cluster"
        assert result["host"] == "cluster-head-svc"
        assert result["ip"] == "10.102.15.119"
        assert result["port"] == 10001

    def test_get_data_throws_error(self):
        """Test get data throws not found error"""
        cluster_dao = ClusterDAO("ray")
        cluster_dao.run = MagicMock()
        cluster_dao.run.side_effect = error_cluster_not_found

        with self.assertRaises(NotFoundError) as context:
            cluster_dao.get("cluster")
        assert 'Error from server (NotFound): services "XXX" not found' == str(
            context.exception
        )


if __name__ == "__main__":
    unittest.main()
