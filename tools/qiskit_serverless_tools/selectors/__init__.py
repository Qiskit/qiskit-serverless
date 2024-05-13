"""
=============================================================
Selectors package (:mod:`qiskit_serverless_tools.selectors`)
=============================================================

.. currentmodule:: qiskit_serverless_tools.selectors

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
