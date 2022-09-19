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
