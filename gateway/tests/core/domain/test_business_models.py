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

"""Unit tests for business model billing names."""

import pytest

from core.domain.business_models import BusinessModel, billing_name_for


@pytest.mark.parametrize(
    "business_model,expected",
    [
        (BusinessModel.SUBSIDIZED, "licensed"),
        (BusinessModel.TRIAL, "trial"),
        (BusinessModel.CONSUMPTION, "consumption"),
    ],
)
def test_billing_name_for_known_models(business_model, expected):
    assert billing_name_for(business_model) == expected


def test_billing_name_for_raises_on_unmapped_model():
    with pytest.raises(ValueError, match="No billing name mapped"):
        billing_name_for("BRAND_NEW_MODEL")


def test_every_business_model_has_a_billing_name():
    """A new BusinessModel constant must come with a billing name."""
    models = [value for name, value in vars(BusinessModel).items() if not name.startswith("_")]

    assert models
    for business_model in models:
        assert billing_name_for(business_model)
