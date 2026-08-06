"""Bounded-cost validation of job arguments against a Qiskit Function's JSON Schema.

Both sides of this validation are untrusted input that the gateway evaluates in the request
thread: the schema comes from whoever owns the function, the instance from whoever runs it. A
JSON Schema ``pattern`` is a regular expression applied to caller input, and Python's
backtracking engine makes that exponential in the length of that input for patterns such as
``^(a+)+$``: 28 characters already take about 8 seconds and every extra character doubles the
time, so a request body of well under 100 bytes can keep a worker busy for hours.

Four rules keep the cost of a validation bounded:

1. ``pattern`` is matched with RE2, which never backtracks, so its matching time is linear in the
   length of the input.

2. ``patternProperties`` is not supported. Its regexes are matched by ``additionalProperties`` and
   ``unevaluatedProperties`` too, inside private jsonschema helpers that cannot be replaced the
   way a keyword can, so allowing the keyword would leave Python's ``re`` reachable.

3. ``$schema`` is only accepted at the top level of the document. jsonschema picks the validator
   class from ``$schema``, including for subschemas, so a ``$schema`` deeper in the document would
   switch back to a class that matches with Python's ``re`` and undo rule 1.

4. The document has a maximum length, which puts a ceiling on how much combinatorial work (nested
   ``anyOf`` / ``allOf``) a schema can spell out.
"""

import functools
from collections.abc import Iterator
from typing import Any

import jsonschema
import re2
from jsonschema import ValidationError

# A schema this long is already far beyond anything hand written, and the worst nested "anyOf"
# that can be spelled out in 64k characters costs about 0.01 seconds to evaluate, which is an
# acceptable ceiling. Note this only bounds a schema that spells the combination out: internal
# "$ref" can still express a much larger one in very few characters.
MAX_SCHEMA_LENGTH = 64 * 1024

# RE2 writes parse errors to stderr by default; we report them to the caller instead.
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.log_errors = False


class UnsupportedSchemaError(Exception):
    """Raised when an arguments schema cannot be evaluated at a bounded cost."""


@functools.lru_cache(maxsize=512)
def _compile(pattern: str):
    """Compile ``pattern`` with RE2. Cached because the same schema is reused on every run."""
    return re2.compile(pattern, options=_RE2_OPTIONS)


def _pattern(validator, patrn, instance, schema):  # pylint: disable=unused-argument
    """RE2 replacement for the ``pattern`` keyword."""
    if validator.is_type(instance, "string") and not _compile(patrn).search(instance):
        yield ValidationError(f"{instance!r} does not match {patrn!r}")


@functools.lru_cache(maxsize=None)
def _with_re2_patterns(base: type) -> type:
    return jsonschema.validators.extend(base, {"pattern": _pattern})


def linear_time_validator_for(schema: Any) -> type:
    """Return the validator class for ``schema`` with the ``pattern`` keyword backed by RE2."""
    return _with_re2_patterns(jsonschema.validators.validator_for(schema))


def _dict_nodes(schema: Any) -> Iterator[tuple[dict, bool]]:
    """Yield every dict in the schema document as ``(node, is_root)``.

    Iterative on purpose: a deeply nested document must not exhaust the stack here.
    """
    stack: list[tuple[Any, bool]] = [(schema, True)]
    while stack:
        node, is_root = stack.pop()
        if isinstance(node, dict):
            yield node, is_root
            stack.extend((value, False) for value in node.values())
        elif isinstance(node, list):
            stack.extend((value, False) for value in node)


def check_arguments_schema(schema: Any, schema_str: str) -> None:
    """Check that ``schema`` can be evaluated at a bounded cost.

    Raises UnsupportedSchemaError when the document is too long, when it uses
    ``patternProperties``, when it switches dialect below the top level, or when a regex in it is
    not valid RE2 syntax (no backreferences, no lookaround), which are the patterns RE2 cannot
    match in linear time.
    """
    if len(schema_str) > MAX_SCHEMA_LENGTH:
        raise UnsupportedSchemaError(f"it is {len(schema_str)} characters long and the maximum is {MAX_SCHEMA_LENGTH}")

    for node, is_root in _dict_nodes(schema):
        if "$schema" in node and not is_root:
            raise UnsupportedSchemaError("'$schema' is only allowed at the top level of the schema")

        if "patternProperties" in node:
            raise UnsupportedSchemaError(
                "'patternProperties' is not supported, use 'properties' with a 'pattern' on the values instead"
            )

        patrn = node.get("pattern")
        if isinstance(patrn, str):
            try:
                _compile(patrn)
            except re2.error as exc:
                detail = exc.args[0].decode(errors="replace") if isinstance(exc.args[0], bytes) else str(exc)
                raise UnsupportedSchemaError(
                    f"the regular expression {patrn!r} is not supported ({detail}). Patterns are "
                    "matched with RE2, which has no backreferences and no lookaround"
                ) from exc
