# This code is a Qiskit project.
#
# (C) Copyright IBM 2024.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""
===========================================================
Utilities (:mod:`quantum_serverless.utils.utils`)
===========================================================

.. currentmodule:: quantum_serverless.utils.utils

Quantum serverless utilities
====================================

.. autosummary::
    :toctree: ../stubs/

    utility functions
"""

import os
import re


def sanitize_file_path(path: str):
    """sanitize file path.

    Args:
        path: file path

    Returns:
        saanitized filepath
    """
    if ".." in path:
        path = path.replace("..", "_")
    pattern = "[^0-9a-zA-Z-_." + os.sep + "]+"
    return re.sub(pattern, "_", path)
