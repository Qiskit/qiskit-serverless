# This code is a Qiskit project.
#
# (C) Copyright IBM 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
=====================================================
Serializers (:mod:`quantum_serverless.train.trainer`)
=====================================================

.. currentmodule:: quantum_serverless.train.trainer

Quantum serverless trainer
==========================

.. autosummary::
    :toctree: ../stubs/

    QiskitScalingConfig
    QiskitTorchTrainer
    get_runtime_session
"""

from .trainer import get_runtime_session, QiskitRuntimeService, QiskitScalingConfig
