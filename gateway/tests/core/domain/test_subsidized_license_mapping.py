"""Unit tests for the temporary SUBSIDIZED to LICENSED mapping."""

from core.domain.business_models import BusinessModel
from core.domain.subsidized_license_mapping import licensed_instead_of_subsidized


def test_subsidized_becomes_licensed():
    assert licensed_instead_of_subsidized(BusinessModel.SUBSIDIZED) == BusinessModel.LICENSED


def test_other_business_models_are_untouched():
    assert licensed_instead_of_subsidized(BusinessModel.TRIAL) == BusinessModel.TRIAL
