# This code is a Qiskit project.
#
# (C) Copyright IBM 2022.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
===================================================
Serializers (:mod:`qiskit_serverless.serializers`)
===================================================

.. currentmodule:: qiskit_serverless.serializers

Qiskit Serverless serializers
==============================

.. autosummary::
    :toctree: ../stubs/

    register_all_serializers
    circuit_serializer
    circuit_deserializer
    service_serializer
    service_deserializer
    get_arguments
"""

from .serializers import (
    register_all_serializers,
    circuit_serializer,
    circuit_deserializer,
    service_serializer,
    service_deserializer,
)

from .program_serializers import get_arguments
