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

A size label is stored and compared in its lowercase canonical form (see
``api.domain.function_sizes.normalize_function_size``), exactly like before
this catalog existed: input is accepted case-insensitively (``"M"``, ``"m"``,
``" M "`` all mean the same size) and the canonical form is lowercase, so
every ``FunctionSize`` row created since the T-shirt-sizes feature shipped
stays valid. Only the labels shown to a human — the Django admin's dropdown,
API error messages — are uppercase. Do not "fix" this to compare uppercase
values without also handling the data migration that would take (see the
design doc for why).
"""

VALID_FUNCTION_SIZES: tuple[str, ...] = ("s", "m", "l", "xl")
