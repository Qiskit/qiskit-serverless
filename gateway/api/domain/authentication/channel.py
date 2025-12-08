"""
This class defines Channels enum for the authentication:
"""

from enum import Enum


class Channel(str, Enum):
    """
    Channel values for the authentication process:
    - IBM_CLOUD
    - IBM_QUANTUM_PLATFORM
    - LOCAL
    """

    IBM_CLOUD = "ibm_cloud"
    IBM_QUANTUM_PLATFORM = "ibm_quantum_platform"
    LOCAL = "local"
