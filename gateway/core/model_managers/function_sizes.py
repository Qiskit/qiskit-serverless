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

"""Function size model manager."""

import logging
from typing import Optional, Self, TYPE_CHECKING

from django.db.models import QuerySet

if TYPE_CHECKING:
    from core.models import ComputeProfiles, FunctionSize, Program as Function

logger = logging.getLogger("core.function_sizes")


class FunctionSizeQuerySet(QuerySet):
    """Function size query set to transform into a manager."""

    def function_sizes(self, function: "Function") -> Self:
        """Return the size rows belonging to one function.

        Args:
            function: Program whose size catalog to return

        Returns:
            QuerySet: the function's size rows
        """
        return self.filter(function=function)

    def get_function_size(self, function: "Function", function_size: Optional[str]) -> Optional["FunctionSize"]:
        """Return a single ``(function, size)`` row.

        The size is normalized to lowercase before the lookup, matching the
        normalization applied on save, so ``"S"`` and ``"s"`` resolve alike.
        At most one row can match, per the ``unique_function_size`` constraint.

        Args:
            function: Program the size belongs to
            function_size: size key (e.g. ``"s"``). May be None.

        Returns:
            FunctionSize | None: the matching row, or None when the size is
            empty or no row exists for it.
        """
        if not function_size:
            return None
        return self.function_sizes(function).filter(function_size=function_size.strip().lower()).first()

    def resolve_compute_profile(
        self, function: "Function", function_size: Optional[str]
    ) -> Optional["ComputeProfiles"]:
        """Resolve a function size to the compute profile it maps to.

        Args:
            function: Program the size belongs to
            function_size: size key (e.g. ``"s"``). May be None.

        Returns:
            ComputeProfiles | None: the mapped profile, or None when the size
            is empty, no row matches, or the matched row has no profile.
        """
        if not function_size:
            return None

        row = self.get_function_size(function, function_size)
        if row is None:
            logger.warning(
                "function='%s' | No function size [%s] defined.",
                function.title,
                function_size,
            )
            return None

        if row.compute_profile_fk is None:
            logger.warning(
                "function='%s' | Function size [%s] has no compute profile assigned.",
                function.title,
                function_size,
            )
            return None

        return row.compute_profile_fk
