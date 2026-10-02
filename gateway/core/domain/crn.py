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

"""The one place that reads the fields of an instance CRN (Cloud Resource Name)."""

from dataclasses import dataclass

ACCOUNT_PREFIX = "a/"

# crn:v1:bluemix:public:quantum-computing:<region>:a/<account>:<instance>::
_REGION_INDEX = 5
_ACCOUNT_INDEX = 6


@dataclass(frozen=True)
class Crn:
    """The parts of an instance CRN the gateway routes on."""

    region: str
    account: str | None

    @classmethod
    def parse(cls, value: str | None) -> "Crn | None":
        """Parse ``value``, or return None if it is empty, not a string or has no region. It never raises.

        A CRN needs at least 7 ``:``-delimited segments (up to and including the account one) and a non-empty
        region. The account loses its ``a/`` prefix when it has one, and is None when empty.
        """
        if not isinstance(value, str):
            return None
        parts = value.split(":")
        if len(parts) <= _ACCOUNT_INDEX or not parts[_REGION_INDEX]:
            return None
        account = parts[_ACCOUNT_INDEX].removeprefix(ACCOUNT_PREFIX) or None
        return cls(region=parts[_REGION_INDEX], account=account)
