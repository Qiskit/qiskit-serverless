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

"""Dao definition for cluster """
# pylint: disable=subprocess-run-check
from subprocess import PIPE, run
import logging
from manager.errors import CommandError, NotFoundError


log = logging.getLogger("cluster_dao")


class AbstractClusterDAOFactory:
    """Factory object for ClusterDAO."""

    def create_instance(self, namespace):
        """Returns ClusterDAO instance"""


class ClusterDAOFactory(AbstractClusterDAOFactory):
    """Factory object for ClusterDAO."""

    def create_instance(self, namespace):
        """Returns ClusterDAO instance"""
        return ClusterDAO(namespace)


class ClusterDAO:
    """Cluster data access object"""

    def __init__(self, namespace: str):
        """
        Initialize cluster dao
        Args:
            namespace: namespace for ray cluster"""
        self.namespace = namespace

    @staticmethod
    def run(command):
        """
        Executes a command line instruction.
        Args:
            command: command to be executed
        Returns:
            execution output
        Raises:
            CommandError
        """
        result = run(
            command, stdout=PIPE, stderr=PIPE, universal_newlines=True, cwd="ray"
        )
        log.info(
            "Executed: %s. Got: [%s] and code [%d]. ERR: [%s]",
            command,
            result.stdout,
            result.returncode,
            result.stderr,
        )
        if result.returncode == 0:  # success
            return result.stdout
        raise CommandError(result.stderr)

    def get_all(self):
        """
        Obtains all ray clusters available in kubernetes.

        Returns:
            List of clusters
        """
        log.info("Get all clusters.")
        get_clusters_command = [
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "rayclusters.ray.io",
            "--no-headers",
            "-o",
            "custom-columns=NAME:metadata.name",
        ]
        result = self.run(get_clusters_command)

        clusters = []
        for line in iter(result.strip().split("\n")):
            log.debug(line)
            cluster = {"name": line}
            clusters.append(cluster)
        return clusters

    def get(self, name):
        """
        Obtains ray cluster details kubernetes.
        Args:
            name: name of the cluster
        Returns:
            Cluster details.
        Raises:
            CommandError, NotFoundError
        """
        log.info("Get details for cluster with name %s", name)
        get_clusters_command = [
            "kubectl",
            "-n",
            self.namespace,
            "get",
            "service",
            str(name) + "-head-svc",
            "-o",
            "custom-columns=IP:.spec.clusterIP",
            "--no-headers",
        ]
        try:
            result = self.run(get_clusters_command)
            host_id = result.strip()
            return {
                "name": name,
                "host": name + "-head-svc",
                "ip": host_id,
                "port": 10001,
            }
        except CommandError as err:
            if "NotFound" in str(err):
                raise NotFoundError(str(err)) from err
            raise err
