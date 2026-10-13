"""Unit tests for Crn.parse."""

from core.domain.crn import Crn, regional_base_url


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


BASE = "https://quantum.test.cloud.ibm.com"


def test_regional_base_url_prefixes_a_non_default_region():
    crn = "crn:v1:bluemix:public:quantum-computing:eu-de:a/acct:inst::"
    assert regional_base_url(BASE, crn, "us-east") == "https://eu-de.quantum.test.cloud.ibm.com"


def test_regional_base_url_keeps_the_bare_host_for_the_default_region_or_an_unparseable_crn():
    crn = "crn:v1:bluemix:public:quantum-computing:us-east:a/acct:inst::"
    assert regional_base_url(BASE, crn, "us-east") == BASE
    assert regional_base_url(BASE, "not-a-crn", "us-east") == BASE
    assert regional_base_url(BASE, None, "us-east") == BASE
