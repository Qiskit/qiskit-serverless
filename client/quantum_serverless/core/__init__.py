"""
============================================
Core module (:mod:`quantum_serverless.core`)
============================================

.. currentmodule:: quantum_serverless.core

This module contains an :class:`QuantumServerless`
which is the main class for managing serverless execution.

Quantum serverless core module classes and functions
====================================================

.. autosummary::
    :toctree: ../stubs/

    QuantumServerless
"""

from .quantum_serverless import QuantumServerless
from .provider.cluster import Cluster
from .decorators import remote, get, put
