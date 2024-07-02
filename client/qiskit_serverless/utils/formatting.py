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
==========================================================
Json utilities (:mod:`qiskit_serverless.utils.formatting`)
==========================================================

.. currentmodule:: qiskit_serverless.utils.formatting

Qiskit Serverless formatting utilities
======================================

.. autosummary::
    :toctree: ../stubs/

    format_provider_name_and_title
"""
from typing import Tuple, Union


def format_provider_name_and_title(
    request_provider, title
) -> Tuple[Union[str, None], str]:
    """
    This method returns provider_name and title from a title with / if it contains it
    """
    if request_provider:
        return request_provider, title

    title_split = title.split("/")
    if len(title_split) == 1:
        return None, title_split[0]

    return title_split[0], title_split[1]
