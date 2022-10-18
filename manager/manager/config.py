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

"""Application configurations"""
from os import getenv


class Config:
    """Base configuration"""

    TESTING = False
    NAMESPACE = getenv("NAMESPACE")


class ProductionConfig(Config):
    """Production configuration"""

    CLUSTER_DAO_FACTORY = "manager.cluster_dao.ClusterDAOFactory"


class DevelopmentConfig(Config):
    """Development configuration"""

    CLUSTER_DAO_FACTORY = "manager.cluster_dao.ClusterDAOFactory"


# def validate_config(config):
#    """ Validates the configuration """
#    if config.get("NAMESPACE") is None:
#        raise ConfigurationError
