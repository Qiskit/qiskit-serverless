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

"""Tests for api calls"""
import unittest
from unittest import TestCase
from manager.app import app


class TestApi(TestCase):
    """Test API"""

    def test_cluster_api_get_all(self):
        """Test successful get all api call"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactorySuccess",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-manager/cluster/")
        data = response.json
        # assert
        assert response.status_code == 200
        assert data == [{"name": "cluster-a"}, {"name": "serverless-cluster"}]

    def test_cluster_api_get(self):
        """Test successful get cluster details api call"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactorySuccess",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-manager/cluster/cluster-a")
        data = response.json
        # assert
        assert response.status_code == 200
        assert data == {
            "name": "cluster-a",
            "host": "cluster-a-ray-head",
            "port": 10001,
            "ip": "127.0.0.1",
        }

    def test_cluster_api_get_all_internal_error(self):
        """Test status code for get all api call with command error"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-manager/cluster/")
        # assert
        assert response.status_code == 500

    def test_cluster_api_get_command_error(self):
        """Test status code for get cluster details api call with command error"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-manager/cluster/cluster-a")
        # assert
        assert response.status_code == 500

    def test_cluster_api_get_not_found_error(self):
        """Test status code for get cluster details when the cluster is not found"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryNotFoundError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-manager/cluster/cluster-a")
        print(response.status_code)
        # assert
        assert response.status_code == 404


if __name__ == "__main__":
    unittest.main()
