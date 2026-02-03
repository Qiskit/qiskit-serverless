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
Utilities (:mod:`qiskit_serverless.utils.utils`)
===========================================================

.. currentmodule:: qiskit_serverless.utils.utils

Qiskit Serverless utilities
====================================

.. autosummary::
    :toctree: ../stubs/

    utility functions
"""

import os
import re


def sanitize_file_path(path: str):
    """sanitize file path.
    Sanitization:
        character string '..' is replaced to '_'.
        character except '0-9a-zA-Z-_.' and directory delimiter('/' or '\')
            is replaced to '_'.

    Args:
        path: file path

    Returns:
        sanitized filepath
    """
    if ".." in path:
        path = path.replace("..", "_")
    pattern = "[^0-9a-zA-Z-_." + os.sep + "]+"
    return re.sub(pattern, "_", path)
