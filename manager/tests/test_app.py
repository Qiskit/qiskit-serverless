"""Tests for api calls"""
import json
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
        response = tester.get("/quantum-serverless-middleware/cluster/")
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
        response = tester.get("/quantum-serverless-middleware/cluster/cluster-a")
        data = response.json
        # assert
        assert response.status_code == 200
        assert data == {
            "name": "cluster-a",
            "host": "cluster-a-ray-head",
            "port": 10001,
            "ip": "127.0.0.1",
        }

    def test_cluster_api_create(self):
        """Test successful create cluster api call"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactorySuccess",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.post(
            "/quantum-serverless-middleware/cluster/",
            data=json.dumps({"name": "bb"}),
            content_type="application/json",
        )
        data = response.json
        print(data)
        # assert
        assert response.status_code == 201
        assert data == {"name": "cluster-a"}

    def test_cluster_api_delete(self):
        """Test successful delete api call"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactorySuccess",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.delete("/quantum-serverless-middleware/cluster/cluster-a")
        # assert
        assert response.status_code == 204

    def test_cluster_api_get_all_internal_error(self):
        """Test status code for get all api call with command error"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-middleware/cluster/")
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
        response = tester.get("/quantum-serverless-middleware/cluster/cluster-a")
        # assert
        assert response.status_code == 500

    def test_cluster_api_create_command_error(self):
        """Test status code for create api call with command error"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.post(
            "/quantum-serverless-middleware/cluster/",
            data=json.dumps({"name": "bb"}),
            content_type="application/json",
        )
        # assert
        assert response.status_code == 500

    def test_cluster_api_delete_command_error(self):
        """Test status code for delete api call with command error"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.delete("/quantum-serverless-middleware/cluster/cluster-a")
        # assert
        assert response.status_code == 500

    def test_cluster_api_create_validation_error(self):
        """Test status code for invalid input(name not in lowercase) when creating cluster"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.post(
            "/quantum-serverless-middleware/cluster/",
            data=json.dumps({"name": "AA"}),
            content_type="application/json",
        )
        # assert
        assert response.status_code == 400

    def test_cluster_api_create_validation_error_length(self):
        """Test status code for invalid input(name loo long) when creating cluster"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryCommandError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.post(
            "/quantum-serverless-middleware/cluster/",
            data=json.dumps(
                {"name": "aaaaaaaaaabbbbbbbbbbccccccccccddddddddddeeeeeeeeee1234"}
            ),
            content_type="application/json",
        )
        # assert
        assert response.status_code == 400

    def test_cluster_api_get_not_found_error(self):
        """Test status code for get cluster details when the cluster is not found"""
        # arrange
        app.config.update(
            CLUSTER_DAO_FACTORY="tests.test_util_dao.ClusterDAOFactoryNotFoundError",
            NAMESPACE="ray",
        )
        tester = app.test_client(self)
        # act
        response = tester.get("/quantum-serverless-middleware/cluster/cluster-a")
        print(response.status_code)
        # assert
        assert response.status_code == 404


if __name__ == "__main__":
    unittest.main()
