"""Utility class containing mocks for tests."""
from unittest.mock import MagicMock
from manager.cluster_dao import ClusterDAO, AbstractClusterDAOFactory
from manager.errors import CommandError, NotFoundError


def error_in_command(*args):
    """Mock for command error"""
    raise CommandError("Error in command")


def error_cluster_not_found(*args):
    """Mock for cluster not found error."""
    raise NotFoundError('Error from server (NotFound): services "XXX" not found')


class ClusterDAOFactorySuccess(AbstractClusterDAOFactory):
    """Factory object for ClusterDAO."""

    def create_instance(self, namespace):
        """Returns ClusterDAO instance"""
        cluster_dao = ClusterDAO(namespace)
        cluster_dao.get_all = MagicMock()
        # mock successful get all
        cluster_dao.get_all.return_value = [
            {"name": "cluster-a"},
            {"name": "serverless-cluster"},
        ]

        # mock successful get
        cluster_dao.get = MagicMock()
        cluster_dao.get.return_value = {
            "name": "cluster-a",
            "host": "cluster-a-ray-head",
            "ip": "127.0.0.1",
            "port": "10001",
        }
        # mock successful create
        cluster_dao.create = MagicMock()
        cluster_dao.create.return_value = {"name": "cluster-a"}

        # mock successful delete
        cluster_dao.delete = MagicMock()
        cluster_dao.delete.return_value = None

        return cluster_dao


class ClusterDAOFactoryCommandError(AbstractClusterDAOFactory):
    """Factory object for ClusterDAO."""

    def create_instance(self, namespace):
        """Returns ClusterDAO instance"""
        cluster_dao = ClusterDAO(namespace)
        cluster_dao.get_all = MagicMock()
        # mock error in get all
        cluster_dao.get_all.side_effect = error_in_command

        # mock error in get
        cluster_dao.get = MagicMock()
        cluster_dao.get.side_effect = error_in_command

        # mock error in create
        cluster_dao.create = MagicMock()
        cluster_dao.create.side_effect = error_in_command

        # mock error in delete
        cluster_dao.delete = MagicMock()
        cluster_dao.delete.side_effect = error_in_command

        return cluster_dao


class ClusterDAOFactoryNotFoundError(AbstractClusterDAOFactory):
    """Factory object for ClusterDAO."""

    def create_instance(self, namespace):
        """Returns ClusterDAO instance"""
        cluster_dao = ClusterDAO(namespace)

        # mock error in get
        cluster_dao.get = MagicMock()
        cluster_dao.get.side_effect = error_cluster_not_found

        # mock error in delete
        cluster_dao.delete = MagicMock()
        cluster_dao.delete.side_effect = error_cluster_not_found

        return cluster_dao
