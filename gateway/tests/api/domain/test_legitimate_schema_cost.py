"""What legitimate schemas actually cost, measured against the CPU budget the isolation gives them.

"Is one second too short?" is answered by a measurement rather than by a proof, so this file holds
the measurement and repeats it on every run instead of leaving it in a review comment. The profiles
are the most expensive legitimate shapes found: the largest arguments the limits allow (a 1 MB batch
of encoded circuits), a schema wide enough to approach MAX_SCHEMA_NODES, and uniqueItems over
thousands of objects.

Each profile asserts two things, and the first matters more than the second:

- It goes through the real isolation with no limit firing, and still tells a valid payload from an
  invalid one. If the budget were too short, this is the assertion that would fail, and it would
  fail with UnsupportedSchemaError naming "CPU time".
- The CPU time it spends stays far under the budget. Measured with time.process_time rather than the
  wall clock on purpose: CPU time is what RLIMIT_CPU counts, and unlike elapsed time it does not
  inflate when the runner is busy, which is what made earlier wall-clock assertions in this feature
  fail on CPU-throttled CI runners.

To see the figures rather than just the pass: pytest tests/api/domain/test_legitimate_schema_cost.py -s
"""

import base64
import json
import time

import jsonschema
import pytest

from api.domain.arguments_schema import (  # pylint: disable=protected-access
    MAX_SCHEMA_NODES,
    _cpu_limit_seconds,
    _validator,
    exceeds_max_nodes,
    max_arguments_length,
    validate_arguments_in_isolation,
)

# Fraction of the CPU budget a legitimate profile is allowed to spend. Deliberately loose: the
# slowest profile below measures around 15 ms against a 1 second budget, so this leaves more than an
# order of magnitude of headroom for slower hardware while still catching a real regression, such as
# the stock uniqueItems coming back, which took 32 seconds on 8000 objects.
_BUDGET_FRACTION = 0.25


def _circuit(index: int) -> str:
    """A distinct string the size of one encoded 100 qubit circuit, about 39 KB of base64.

    Distinct per index so that a batch of them passes uniqueItems: a duplicate would be rejected on
    the spot and the profile would measure an early exit instead of a full validation.
    """
    return base64.b64encode(f"circuit-{index}-".encode() + b"x" * 29000).decode()


def _batch() -> list:
    """A batch of circuits adding up to about 1 MB once encoded.

    That was the whole of MAX_ARGUMENTS_LENGTH when these profiles were written, and the figure is
    kept rather than raised with the limit: what these tests watch is the cost per unit of input,
    which is linear, so a bigger batch would spend proportionally longer without exercising anything
    new. specs/ARGUMENTS_LIMIT.md carries the measurements across the whole range.
    """
    return [_circuit(i) for i in range(26)]


def _typical_vendor_profile():
    """A hand-written vendor schema against a 1 MB batch of circuits."""
    schema = {
        "type": "object",
        "required": ["backend", "shots", "circuits"],
        "properties": {
            "backend": {"type": "string", "pattern": "^ibm_[a-z0-9_]+$"},
            "shots": {"type": "integer", "minimum": 1, "maximum": 100000},
            "optimization_level": {"enum": [0, 1, 2, 3]},
            "resilience_level": {"enum": [0, 1, 2]},
            "mode": {"enum": ["batch", "session", "single"]},
            "rep_delay": {"type": "number", "minimum": 0},
            "job_tags": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "email": {"type": "string", "format": "email"},
            "created": {"type": "string", "format": "date-time"},
            "layout": {"type": "array", "items": {"type": "integer"}},
            "twirling": {"type": "object", "properties": {"gates": {"type": "boolean"}}},
            "circuits": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
    }
    valid = {
        "backend": "ibm_torino",
        "shots": 4096,
        "optimization_level": 3,
        "resilience_level": 1,
        "mode": "batch",
        "rep_delay": 0.0005,
        "job_tags": ["nightly"],
        "email": "user@example.com",
        "created": "2026-08-18T10:00:00Z",
        "layout": list(range(100)),
        "twirling": {"gates": True},
        "circuits": _batch(),
    }
    invalid = dict(valid, backend="NOT A BACKEND")
    return schema, valid, invalid


def _wide_schema_profile():
    """A schema approaching MAX_SCHEMA_NODES, with internal references, against 1 MB of arguments."""
    schema = {
        "type": "object",
        "$defs": {
            "checked_string": {"type": "string", "minLength": 1, "maxLength": 100000},
            "bounded_int": {"type": "integer", "minimum": 0, "maximum": 1000000},
        },
        "properties": {
            **{
                f"field_{i}": {"$ref": "#/$defs/checked_string" if i % 2 else "#/$defs/bounded_int"} for i in range(140)
            },
            "circuits": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
            "nested": {"type": "object", "properties": {f"n_{i}": {"type": "number"} for i in range(50)}},
        },
    }
    valid = {
        **{f"field_{i}": ("x" * 50 if i % 2 else i) for i in range(140)},
        "circuits": _batch(),
        "nested": {f"n_{i}": i * 1.5 for i in range(50)},
    }
    invalid = dict(valid, field_1=12345)  # an odd field is a string, so an integer must be rejected
    return schema, valid, invalid


def _unique_items_profile():
    """Thousands of objects under uniqueItems, the keyword this module replaces to keep it cheap."""
    schema = {"type": "array", "uniqueItems": True, "items": {"type": "object"}}
    valid = [{"i": i, "label": f"item-{i}"} for i in range(4000)]
    invalid = valid[:-1] + [valid[0]]
    return schema, valid, invalid


PROFILES = [
    ("typical vendor schema, 1 MB batch of circuits", _typical_vendor_profile),
    ("wide schema with internal references, 1 MB of arguments", _wide_schema_profile),
    ("uniqueItems over 4000 objects", _unique_items_profile),
]


@pytest.mark.parametrize("label,builder", PROFILES, ids=[p[0] for p in PROFILES])
def test_a_legitimate_schema_validates_well_inside_the_cpu_budget(label, builder):
    """Each profile validates through the real isolation with no limit firing, and costs a small
    fraction of the CPU budget while doing it."""
    schema, valid, invalid = builder()
    valid_str = json.dumps(valid)
    # A realism guard rather than a tight bound: these profiles are about 1 MB against a limit that is
    # now 32 by default, so this only catches a profile grown past what a caller could ever send.
    assert len(valid_str) <= max_arguments_length()
    assert not exceeds_max_nodes(schema), f"the profile itself must stay under {MAX_SCHEMA_NODES} nodes"

    # The real path, isolation included. UnsupportedSchemaError here is the failure that would mean
    # the budget is too short for a legitimate schema.
    validate_arguments_in_isolation(schema, valid_str)
    with pytest.raises(jsonschema.ValidationError):
        validate_arguments_in_isolation(schema, json.dumps(invalid))

    # The cost, measured where it can be attributed to this process rather than to the child.
    validator = _validator(schema)
    parsed = json.loads(valid_str)
    start = time.process_time()
    errors = list(validator.iter_errors(parsed))
    cpu_seconds = time.process_time() - start
    assert not errors

    budget = _cpu_limit_seconds()
    print(
        f"\n{label}: {cpu_seconds * 1000:.2f} ms of CPU, "
        f"{budget / cpu_seconds:,.0f}x under the {budget}s budget "
        f"(schema {len(json.dumps(schema)):,} chars, arguments {len(valid_str):,} chars)"
    )
    assert cpu_seconds < budget * _BUDGET_FRACTION
