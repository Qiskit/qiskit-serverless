"""Unit tests for Crn.parse."""

from core.domain.crn import Crn


def test_parses_region_and_account():
    crn = Crn.parse("crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:guid::")
    assert crn == Crn(region="eu-de", account="acct")


def test_account_without_prefix_is_kept_as_is():
    assert Crn.parse("crn:v1:bluemix:public:quantum-computing:us-east:acct:guid::").account == "acct"


def test_empty_none_and_malformed_return_none():
    for value in ("", None, "crn:test:123", "crn:v1:bluemix:public:quantum-computing:us-east", 42):
        assert Crn.parse(value) is None


def test_empty_region_returns_none():
    assert Crn.parse("crn:v1:bluemix:public:quantum-computing::a/acct:guid::") is None
