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
ServerlessError exception for function developers
"""
from typing import Any


class ServerlessError(Exception):
    """Base exception that can be used by function developers."""

    def __init__(self, code: str, message: str, details: Any):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return f"[{self.code}] {self.message}\n{self.details}"
