"""Validation of job arguments against a Qiskit Function's JSON Schema.

Both sides of this validation are untrusted input that the gateway evaluates in the request
thread: the schema comes from whoever owns the function, the instance from whoever runs it. A
JSON Schema ``pattern`` is a regular expression applied to caller input, and Python's backtracking
engine makes that exponential in the length of that input for patterns such as ``^(a+)+$``, so a
request body of well under 100 bytes can keep a worker busy for hours. jsonschema also spends
unbounded cost in places a budget on subschemas cannot see, such as ``uniqueItems`` and
``unevaluatedProperties``, which never descend even once.

Bounding that cost from inside jsonschema was tried and refuted five times: keywords whose cost
lives in private module level helpers no subclass can reach, a ``$schema`` below the top level
restoring the stock (backtracking) validator class on a reference, the size of a compiled regex
program, and memory, which nothing inside jsonschema bounds at all.

The cost is now bounded by the operating system instead, in a forked child (``api.domain.isolated``).
``RLIMIT_CPU`` kills a runaway regex at 1.00s with ``SIGXCPU``, and ``RLIMIT_AS`` turns a large
allocation into a catchable ``MemoryError`` at 0.38s on Linux. ``RLIMIT_AS`` does not fire on macOS,
where base address space is 425 GB against 25 MB on Linux, so that half of the protection degrades
in development and applies in production.

What remains in this module is the text limits applied before anything is evaluated: a maximum
length for the schema document and for the arguments, a maximum nesting depth for both, and a
maximum count of subschemas in the document. These bound the input rather than the cost of
evaluating it, and they run before the child is even forked.
"""

import json
from typing import Any

import jsonschema
from referencing import Registry

from api.domain.isolated import IsolationError, run_isolated

# A schema this long is already far beyond anything hand written, and the worst nested "anyOf"
# that can be spelled out in 64k characters costs about 0.01 seconds to evaluate, which is an
# acceptable ceiling. Note this only bounds a schema that spells the combination out: internal
# "$ref" can still express a much larger one in very few characters.
MAX_SCHEMA_LENGTH = 64 * 1024

# Maximum length of the arguments a caller may send. Several keywords cost more the longer the
# instance is, and without this the ceiling would be DATA_UPLOAD_MAX_MEMORY_SIZE (2.5 MB by
# default). This is defence in depth rather than the main protection: the keyword that actually
# grew faster than its input, "uniqueItems", is replaced below, and the deadline covers the rest.
# So the figure is chosen to leave legitimate callers alone. Arguments are validated in the form
# QiskitObjectsEncoder produces, where a single 100 qubit, depth 100 circuit is about 39 KB of
# base64, so a limit in the tens of kilobytes would reject an ordinary batch of circuits.
MAX_ARGUMENTS_LENGTH = 1024 * 1024

# Maximum nesting depth of the schema document and of the instance. jsonschema recurses once per
# level of each, and CPython gives up at a nesting depth of about 180, which a few kilobytes of
# either can reach. Anything hand written stays in single digits, so this leaves plenty of room
# while keeping the recursion well short of the interpreter's limit.
MAX_DOCUMENT_DEPTH = 64

# Maximum number of subschemas the document may contain. Memory use scales with the number of
# branches times the size of the instance, because "anyOf" accumulates one error per branch and
# jsonschema builds each message with repr(instance): 2000 branches against 500 KB of arguments
# cost 1018 MB, measured. At this limit the same arguments cost about a tenth of that. This is the
# half of the memory protection that works everywhere, since RLIMIT_AS does not bound on macOS.
MAX_SCHEMA_NODES = 200

# Formats the gateway asserts. jsonschema treats "format" as an annotation and checks nothing
# unless a checker is attached, so without this a vendor's "format" would silently reject nothing.
# Only checkers that cost no more than the length of their input are listed: "regex" is left out
# because it compiles caller input with Python's backtracking engine, the one thing rule 1 exists
# to keep out of reach, and "idn-hostname" because its cost lives in a third party library. Any
# other format stays an annotation, which is what JSON Schema says an unknown format is.
_ASSERTED_FORMATS = ("date", "email", "idn-email", "ipv4", "ipv6", "uuid")
_FORMAT_CHECKER = jsonschema.FormatChecker(formats=_ASSERTED_FORMATS)

# References are never retrieved: this registry has no retrieval hook, so an external "$ref" raises
# Unresolvable instead of causing a request or a file read. Verified with a spy on socket.connect:
# no socket calls with this registry, getaddrinfo plus connect with jsonschema's default one. Note
# it is not empty, despite the name: jsonschema does SPECIFICATIONS.combine(registry), so the
# packaged metaschemas do resolve. What it stops is going out to the network.
_NO_EXTERNAL_REFS = Registry()


class UnsupportedSchemaError(Exception):
    """Raised when an arguments schema cannot be evaluated at a bounded cost."""


def exceeds_max_depth(value: Any) -> bool:
    """Whether ``value`` nests deeper than ``MAX_DOCUMENT_DEPTH``.

    Walks iteratively and stops at the first node past the limit, so it cannot exhaust the stack
    itself, and applies to the instance as much as to the schema: the ordinary way to describe a
    tree is a recursive schema, and there the depth that decides the cost is the caller's.
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DOCUMENT_DEPTH:
            return True
        if isinstance(node, dict):
            stack.extend((item, depth + 1) for item in node.values())
        elif isinstance(node, list):
            stack.extend((item, depth + 1) for item in node)
    return False


def exceeds_max_nodes(schema: Any) -> bool:
    """Whether ``schema`` contains more than ``MAX_SCHEMA_NODES`` subschemas.

    Counts dicts and booleans, which over-approximates: a boolean that is a keyword value
    such as ``uniqueItems: true`` or ``required: false`` will also be counted, but that is
    harmless because a legitimate schema is nowhere near 200 nodes, and the alternative
    approach of distinguishing schema positions from keyword positions is what made the
    previous approach unworkable. Walks iteratively and stops as soon as the limit is
    passed, so it cannot be expensive itself.
    """
    seen = 0
    stack: list[Any] = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, (dict, bool)):
            seen += 1
            if seen > MAX_SCHEMA_NODES:
                return True
            if isinstance(node, dict):
                stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _require_schema_shape(schema: Any) -> None:
    """Refuse a schema that is not an object or a boolean.

    jsonschema's own entry points assume one or the other: ``validator_for`` tests
    ``"$schema" not in schema``, which raises TypeError on a JSON number or null, and nothing
    downstream catches it, so the request came out as a 500 instead of a rejection.
    """
    if not isinstance(schema, (dict, bool)):
        raise UnsupportedSchemaError(f"a JSON Schema must be an object or a boolean, not {type(schema).__name__}")


def _validator(schema: Any):
    """Build a stock jsonschema validator for ``schema`` against the no-retrieval registry."""
    return jsonschema.validators.validator_for(schema)(
        schema, registry=_NO_EXTERNAL_REFS, format_checker=_FORMAT_CHECKER
    )


def find_external_ref(node: Any) -> str | None:
    """Return the first reference in ``node`` that points outside the schema document.

    Only same-document references ("#" fragments) are allowed. Anything else would make the
    validator fetch a URL or read a file when the schema is later used, so it is rejected at upload
    rather than at validation time, when the caller could no longer do anything about it.

    "$dynamicRef" and "$recursiveRef" resolve references just like "$ref", so they are checked too.
    Missing them did not allow a fetch, since validation runs against a registry with no retrieval
    hook, but it did let a function be stored that raises Unresolvable on every single run.

    Recursive on purpose, unlike the walks above: it only ever runs inside the isolation, where a
    document deep enough to exhaust the stack costs a rejection rather than a failed request.
    """
    if isinstance(node, dict):
        for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
            ref = node.get(keyword)
            if isinstance(ref, str) and not ref.startswith("#"):
                return ref
        for value in node.values():
            found = find_external_ref(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_external_ref(value)
            if found is not None:
                return found
    return None


def validate_arguments_in_isolation(schema: Any, arguments_str: str) -> None:
    """Parse ``arguments_str`` and validate it against ``schema`` in a child with hard limits.

    The caller applies the text limits on the schema first. Parsing the arguments happens inside
    the child on purpose: json.loads raises RecursionError on a few kilobytes of nesting and
    ValueError on an integer with more than 4300 digits, both from caller input, and outside the
    isolation each of those came out of the request as a 500.

    Raises:
        UnsupportedSchemaError: if the schema cannot be evaluated, the arguments are not JSON or
            are nested too deep, or a limit fired.
        jsonschema.ValidationError: if the arguments do not match the schema, with ``path`` set.
    """
    _require_schema_shape(schema)

    def work():
        try:
            arguments = json.loads(arguments_str)
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            return {"unusable": f"arguments are not valid JSON ({type(exc).__name__})"}
        if exceeds_max_depth(arguments):
            return {"unusable": f"arguments are nested more than {MAX_DOCUMENT_DEPTH} levels deep"}
        try:
            _validator(schema).validate(arguments)
            return {"valid": True}
        except jsonschema.ValidationError as exc:
            return {"valid": False, "message": exc.message, "path": [str(part) for part in exc.path]}
        except Exception as exc:  # pylint: disable=broad-except
            # SchemaError, Unresolvable, RecursionError, UnknownType, and the TypeError and
            # AttributeError a malformed keyword raises. Every one of these used to be a 500.
            return {"unusable": f"{type(exc).__name__}: {exc}"}

    answer = _answer_from_child(work)
    if "unusable" in answer:
        raise UnsupportedSchemaError(answer["unusable"])
    if not answer["valid"]:
        raise jsonschema.ValidationError(answer["message"], path=answer["path"])


def check_uploaded_schema_in_isolation(schema_str: str) -> None:
    """Check that ``schema_str`` is a schema the gateway can store and later evaluate.

    Everything that touches the document runs in the child, because each step here has been seen to
    raise out of the request: json.loads gives RecursionError on 1500 levels of nesting,
    validator_for gives TypeError on an unhashable "$schema", and check_schema gives
    UnicodeEncodeError on a pattern holding a lone surrogate.

    This is the only place the metaschema check runs. It used to run on every request too, which
    cost 89 ms for a 63 KB schema and put a ceiling of about 22 requests a second on the gateway.

    Raises:
        UnsupportedSchemaError: with a message meant for whoever is uploading the function.
    """

    def work():  # pylint: disable=too-many-return-statements
        try:
            schema = json.loads(schema_str)
        except (json.JSONDecodeError, ValueError, RecursionError):
            return {"error": "it must be valid JSON"}
        if not isinstance(schema, (dict, bool)):
            return {"error": f"a JSON Schema must be an object or a boolean, not {type(schema).__name__}"}
        if exceeds_max_depth(schema):
            return {"error": f"it is nested more than {MAX_DOCUMENT_DEPTH} levels deep"}
        if exceeds_max_nodes(schema):
            return {"error": f"it contains more than {MAX_SCHEMA_NODES} subschemas"}
        external_ref = find_external_ref(schema)
        if external_ref is not None:
            return {
                "error": f"it must not reference external resources: '{external_ref}'. Inline the "
                "definitions or use an internal reference such as '#/$defs/name'"
            }
        try:
            jsonschema.validators.validator_for(schema).check_schema(schema)
        except jsonschema.SchemaError as exc:
            return {"error": f"it is not a valid JSON Schema: {exc.message}"}
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"it cannot be used ({type(exc).__name__}: {exc})"}
        return {"ok": True}

    answer = _answer_from_child(work)
    if "error" in answer:
        raise UnsupportedSchemaError(answer["error"])


def _answer_from_child(work) -> Any:
    """Run ``work`` in the isolation, turning a limit being hit into UnsupportedSchemaError."""
    try:
        return run_isolated(work)
    except IsolationError as exc:
        raise UnsupportedSchemaError(exc.reason) from exc
