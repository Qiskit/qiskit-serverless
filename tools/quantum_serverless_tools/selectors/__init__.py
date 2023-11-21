"""
=============================================================
Selectors package (:mod:`quantum_serverless_tools.selectors`)
=============================================================

.. currentmodule:: quantum_serverless_tools.selectors

This package contains functionality for automatically
selecting hardware, given some criteria.

Selector package classes and functions
======================================

.. autosummary::
    :toctree: ../stubs/

    IBMQPUSelector
    IBMLeastBusyQPUSelector
    IBMLeastNoisyQPUSelector
"""

from .qpu import (
    IBMQPUSelector,
    IBMLeastBusyQPUSelector,
    IBMLeastNoisyQPUSelector,
)

__all__ = [
    "IBMQPUSelector",
    "IBMLeastBusyQPUSelector",
    "IBMLeastNoisyQPUSelector",
]
