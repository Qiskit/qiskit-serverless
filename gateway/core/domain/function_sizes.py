# This code is part of a Qiskit project.
#
# (C) IBM 2026
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""The closed catalog of valid function size labels.

A plain module with no Django import on purpose: ``main/settings.py`` needs this list
to validate ``DEFAULT_FUNCTION_SIZE`` at import time, and settings.py is read before
Django's app registry exists, so it cannot import anything that defines a model (doing
so raises ``AppRegistryNotReady``). ``FunctionSize`` (``core.models``) re-exports this
same tuple as ``FunctionSize.VALID_SIZES`` for application code, matching how ``Job``
and ``Program`` carry their own catalogs as class attributes; this module is only about
being importable before that model can be.
"""

VALID_SIZES: tuple[str, ...] = ("S", "M", "L", "XL")
