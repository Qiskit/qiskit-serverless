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
Retrieve serverless client version from file.
"""

import os

_version_path = os.path.join(os.path.dirname(__file__), "VERSION.txt")

with open(_version_path, encoding="utf-8") as f:
    __version__ = f.read().strip()
