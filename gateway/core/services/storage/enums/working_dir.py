"""
This class defines WorkingDir enum for Storage services:
"""

from enum import Enum


class WorkingDir(Enum):
    """
    This Enum has the values:
        USER_STORAGE
        PROVIDER_STORAGE

    Both values are being used to identify in
        Storages service the path to be used by
        the user or the provider
    """

    USER_STORAGE = 1
    PROVIDER_STORAGE = 2
