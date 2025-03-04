"""This file contains the enums used in the project."""

from enum import Enum


class Channel(str, Enum):
    """
    This enum identifies the different types of channels with that a user can
    authenticate against.
    """

    LOCAL = "local"
    IBM_QUANTUM = "ibm_quantum"
    IBM_CLOUD = "ibm_cloud"
