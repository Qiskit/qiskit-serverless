"""
This class defines Channels enum for the authentication:
"""

from enum import Enum


class Channel(str, Enum):
    """
    Channel values for the authentication process:
    - IBM_QUANTUM
    - IBM_QUANTUM_PLATFORM
    - LOCAL
    """

    IBM_QUANTUM = "ibm_quantum"
    IBM_QUANTUM_PLATFORM = "ibm_quantum_platform"
    LOCAL = "local"
