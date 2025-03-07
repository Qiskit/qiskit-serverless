"""
This class defines Channels enum for the authentication:
"""

from enum import Enum


class Channel(str, Enum):
    """
    Channel values for the authentication process:
    - IBM_QUANTUM
    - IBM_CLOUD
    - LOCAL
    """

    IBM_QUANTUM = "ibm_quantum"
    IBM_CLOUD = "ibm_cloud"
    LOCAL = "local"
