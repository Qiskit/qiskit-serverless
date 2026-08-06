"""Bounded-cost validation of job arguments against a Qiskit Function's JSON Schema.

Both sides of this validation are untrusted input that the gateway evaluates in the request
thread: the schema comes from whoever owns the function, the instance from whoever runs it. A
JSON Schema ``pattern`` is a regular expression applied to caller input, and Python's
backtracking engine makes that exponential in the length of that input for patterns such as
``^(a+)+$``: 28 characters already take about 8 seconds and every extra character doubles the
time, so a request body of well under 100 bytes can keep a worker busy for hours.

Five rules keep the cost of a validation bounded:

1. ``pattern`` is matched with RE2, which never backtracks, so its matching time is linear in the
   length of the input.

2. ``patternProperties`` is not supported. Its regexes are matched by ``additionalProperties`` and
   ``unevaluatedProperties`` too, inside private jsonschema helpers that cannot be replaced the
   way a keyword can, so allowing the keyword would leave Python's ``re`` reachable.

3. ``$schema`` is only accepted at the top level of the document. jsonschema picks the validator
   class from ``$schema``, including for subschemas, so a ``$schema`` deeper in the document would
   switch back to a class that matches with Python's ``re`` and undo rule 1. It is also what keeps
   rule 5 in place, since ``evolve`` falls back to the current class only while the dialect does
   not change.

4. The document has a maximum length, which puts a ceiling on how much combinatorial work (nested
   ``anyOf`` / ``allOf``) a schema can spell out literally.

5. A validation may only visit a bounded number of subschemas. Rule 4 alone is not enough: an
   internal ``$ref`` expresses an exponential combination in very few characters, so a 1.3 KB
   document can otherwise keep a worker busy for minutes. The budget bounds the total work
   whatever shape the schema takes, which also covers tricks nobody has thought of yet.

References are never retrieved. The schema is evaluated against an empty registry, so a ``$ref``
pointing outside the document resolves to nothing rather than making the gateway fetch a URL or
read a file. Same-document references keep working: they resolve against the document itself.
"""

import contextvars
import functools
from collections.abc import Iterator
from typing import Any

import jsonschema
import re2
from jsonschema import ValidationError
from referencing import Registry

# A schema this long is already far beyond anything hand written, and the worst nested "anyOf"
# that can be spelled out in 64k characters costs about 0.01 seconds to evaluate, which is an
# acceptable ceiling. Note this only bounds a schema that spells the combination out: internal
# "$ref" can still express a much larger one in very few characters.
MAX_SCHEMA_LENGTH = 64 * 1024

# Maximum number of subschemas a single validation may visit. A realistic arguments schema needs
# single digits (a four-property object with a nested object costs 4), so this leaves three orders
# of magnitude of headroom while capping the worst case at about a tenth of a second.
MAX_VALIDATION_STEPS = 10_000

# References are never retrieved: an empty registry has no retrieval hook, so an external "$ref"
# raises Unresolvable instead of causing a request or a file read.
_NO_EXTERNAL_REFS = Registry()

# Counts the subschemas visited by the validation running in this thread or task. It lives in a
# context variable rather than on the validator because jsonschema builds a fresh validator per
# subschema through "evolve", so instance state would not be shared across the recursion.
_steps = contextvars.ContextVar("arguments_schema_steps", default=0)

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
    # A non-string pattern is a broken schema, not something to compile. Ignoring it here leaves the
    # report to check_schema, instead of raising an unhandled TypeError out of the request.
    if not isinstance(patrn, str):
        return
    if validator.is_type(instance, "string") and not _compile(patrn).search(instance):
        yield ValidationError(f"{instance!r} does not match {patrn!r}")


@functools.lru_cache(maxsize=None)
def _bounded(base: type) -> type:
    """Return ``base`` with RE2 patterns and a ceiling on how many subschemas it may visit."""
    with_re2 = jsonschema.validators.extend(base, {"pattern": _pattern})

    class BoundedValidator(with_re2):
        """Counts every subschema it descends into and gives up once the budget is spent."""

        def descend(self, *args, **kwargs):
            visited = _steps.get() + 1
            if visited > MAX_VALIDATION_STEPS:
                raise UnsupportedSchemaError(
                    f"validating against it visits more than {MAX_VALIDATION_STEPS} subschemas"
                )
            _steps.set(visited)
            yield from super().descend(*args, **kwargs)

    return BoundedValidator


def validate_at_bounded_cost(schema: Any, instance: Any) -> None:
    """Validate ``instance`` against ``schema`` without letting it cost an unbounded amount.

    Patterns are matched with RE2, references are never retrieved, and the number of subschemas
    visited is capped.

    Raises:
        UnsupportedSchemaError: if the validation runs out of budget.
        jsonschema.SchemaError: if the schema is not a valid JSON Schema.
        jsonschema.ValidationError: if the instance does not match the schema.
        referencing.exceptions.Unresolvable: if the schema references something outside itself.
    """
    validator_class = _bounded(jsonschema.validators.validator_for(schema))
    validator_class.check_schema(schema)
    _steps.set(0)
    validator_class(schema, registry=_NO_EXTERNAL_REFS).validate(instance)


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
