"""Validation of job arguments against a Qiskit Function's JSON Schema.

Both sides of this validation are untrusted input that the gateway evaluates in the request
thread: the schema comes from whoever owns the function, the instance from whoever runs it. A
JSON Schema ``pattern`` is a regular expression applied to caller input, and Python's backtracking
engine makes that exponential in the length of that input for patterns such as ``^(a+)+$``, so a
request body of well under 100 bytes can keep a worker busy for hours. jsonschema also spends
unbounded cost in a private helper behind ``uniqueItems`` that never descends into a subschema, so
a budget on subschemas cannot see it either.

Bounding that cost from inside jsonschema was tried and refuted four times: keywords whose cost
lives in private module level helpers no subclass can reach, a ``$schema`` below the top level
restoring the stock (backtracking) validator class on a reference, the size of a compiled regex
program, and memory, which nothing inside jsonschema bounds at all.

The cost is now bounded by the operating system instead, in a forked child (``api.domain.isolated``).
``RLIMIT_CPU`` kills a runaway regex at 1.00s with ``SIGXCPU``, and ``RLIMIT_AS`` turns a large
allocation into a catchable ``MemoryError`` at 0.38s on Linux. ``RLIMIT_AS`` is never set on macOS at
all: the limit is computed from the process's own address space, read from ``/proc/self/status``,
which does not exist there, so that half of the protection degrades in development and applies in
production.

One keyword is still replaced rather than left for the isolation alone to bound: ``uniqueItems``.
jsonschema compares elements pairwise whenever they are not sortable, which any array of objects
triggers, inside a private helper that never descends into a subschema, so it pays its full
quadratic cost within the isolation's CPU budget regardless: 4000 objects took about 8 seconds,
which the isolation would refuse outright even though sending a few thousand of them is ordinary
for a caller. Hashing a canonical form of each element (``_comparison_key``, ``_unique_items``)
answers the same question in one pass instead. Do not delete this as leftover scaffolding: unlike
``pattern``, which the isolation alone now bounds, this is the one place jsonschema still spends
unbounded cost that isolation can only refuse rather than make cheap.

What remains in this module besides that replacement is the text limits applied to the schema
before anything is evaluated: a maximum length for the document, a maximum nesting depth, and a
maximum count of subschemas. Where each one runs depends on the entry point. On the run path
(``validate_arguments_in_isolation``), the caller already holds the schema as a parsed object, so
it applies the length, depth and node count limits itself, before anything is forked; the arguments
get the same length limit there too, but their depth limit cannot run there, since they are still
text at that point and parsing them is itself part of what has to be isolated, so it runs inside
the child, right after ``json.loads``. On the upload path (``check_uploaded_schema_in_isolation``),
only the length limit runs in the caller, because it needs no parsing: the schema is still text
when this module receives it, so ``json.loads`` and the depth and node count checks that follow all
run inside the child instead.
"""

import json
from typing import Any
from urllib.parse import unquote

import jsonschema
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from referencing import Registry

from api.domain.isolated import IsolationError, run_isolated

# A schema this long is already far beyond anything hand written. MAX_SCHEMA_NODES below already
# refuses a schema wide enough to make its combinatorial evaluation expensive, so this is defence in
# depth for a document that grows a single node instead of adding more of them, such as a huge
# string literal in "enum" or "pattern": it still bounds the size of the text handled before
# anything is forked. Note this only bounds a schema that spells things out: internal "$ref" can
# still express a much larger one in very few characters.
MAX_SCHEMA_LENGTH = 64 * 1024

# Ceiling on settings.MAX_ARGUMENTS_LENGTH_MB, the longest arguments a caller may send to a function
# that declares a schema. A configured value above this is refused rather than quietly pulled down to
# it, so the limit in force is always the one the deployment asked for or none at all.
#
# 64 is where the validation child's default 128 MB margin still has room to spare. Measured on Linux
# in a container, where RLIMIT_AS actually applies: validating a batch of encoded circuits grows the
# child's address space by about as much as the arguments themselves weigh, so that margin covers
# roughly 127 MB of them and 64 leaves room for a shape twice as dense. It cannot usefully be tighter,
# because cost follows shape rather than length: an array of tiny objects costs eight times as much
# and 0.27 CPU seconds per MB, so the one second budget refuses it at about 3.5 MB, well before any
# length does. specs/ARGUMENTS_LIMIT.md has the tables and the scripts to repeat them.
_MAX_ARGUMENTS_LENGTH_MB = 64


def max_arguments_length() -> int:
    """The longest arguments a caller may send, in bytes.

    Raises:
        ImproperlyConfigured: if the setting is above the ceiling above. ApiConfig.ready calls this at
            startup so that lands as a boot failure rather than as a 500 on the first request.
    """
    if settings.MAX_ARGUMENTS_LENGTH_MB > _MAX_ARGUMENTS_LENGTH_MB:
        raise ImproperlyConfigured(
            f"MAX_ARGUMENTS_LENGTH_MB is {settings.MAX_ARGUMENTS_LENGTH_MB} and the maximum is "
            f"{_MAX_ARGUMENTS_LENGTH_MB}. See specs/ARGUMENTS_LIMIT.md for why, and raise "
            f"ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB first if a caller really needs more."
        )
    return settings.MAX_ARGUMENTS_LENGTH_MB * 1024 * 1024


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

# Bounds for settings.ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB (gateway/main/settings.py), the RLIMIT_AS
# margin given to the forked child (api/domain/isolated.py). Read from settings rather than baked in
# here, so it can be tuned without a code deploy, but a setting is also a way to weaken this by
# configuration, so the value that reaches the child is clamped rather than used as given:
# - MAX guards against reopening the exact failure this module exists to close. Measured in a
#   container at the chart's default limits (2 Gi, 3 CPU, gunicorn --workers=2 --threads=1): a 512 MB
#   margin let a 4 KB schema plus 1 MB of arguments drive one child to 526 MB, and two concurrent
#   such requests, exactly the worker x thread concurrency, added about 960 MB to the cgroup and got
#   a process OOM-killed. Half of that failing value leaves a wide safety margin.
# - MIN keeps the limit from being weakened into uselessness the other way: every legitimate shape
#   tested (a 1 MB batch of encoded circuits, 4000 objects under uniqueItems) passed at 64 MB, so a
#   configured value below that would start rejecting ordinary callers rather than attackers.
_MIN_MEMORY_LIMIT_MB = 64
_MAX_MEMORY_LIMIT_MB = 256

# Bounds for settings.ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS, the RLIMIT_CPU budget given to the child.
# Configurable for the same reason as the memory margin: every legitimate schema measured validates
# in milliseconds, but the figure is a measurement rather than a proof, and a vendor whose schema
# turns out to need longer should be unblocked by changing a value rather than by a code deploy.
# Clamped for a stronger reason than the memory margin, though: this is the whole bound on how much
# work one request can ask for, and no endpoint is rate limited, so raising it multiplies what a
# single caller can spend, one CPU second at a time, without ever creating a job. MIN is 1 because
# RLIMIT_CPU counts whole seconds and 0 would kill the child immediately.
#
# MAX is not reachable under every HTTP server timeout, and that is a second constraint on this value
# that this clamp does not enforce. run_isolated turns the budget into a wall-clock deadline five
# times as long (_WALL_CLOCK_SLOWDOWN_FACTOR in api/domain/isolated.py), so a budget of 5 means a 25
# second deadline, and a deadline reaching gunicorn's --timeout means the arbiter kills the worker at
# the moment the gateway would have answered 400: the caller gets a dropped connection instead of a
# rejection, and every other request on that worker dies with it, since the pod runs --threads=1. So
# the usable maximum depends on the deployment. At the chart's default timeout of 25
# (application.httpServer.timeout, which is also what the deployment values leave in place unless
# they override it) the usable maximum is 3, not 5; a deployment running a longer timeout can use the
# whole range. Raise the timeout before raising this.
_MIN_CPU_LIMIT_SECONDS = 1
_MAX_CPU_LIMIT_SECONDS = 5


def _memory_limit_mb() -> int:
    """The child memory limit from settings, clamped to a safe range."""
    return max(_MIN_MEMORY_LIMIT_MB, min(settings.ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB, _MAX_MEMORY_LIMIT_MB))


def _cpu_limit_seconds() -> int:
    """The child CPU budget from settings, clamped to a safe range."""
    return max(_MIN_CPU_LIMIT_SECONDS, min(settings.ARGUMENTS_SCHEMA_CPU_LIMIT_SECONDS, _MAX_CPU_LIMIT_SECONDS))


# Formats the gateway asserts. jsonschema treats "format" as an annotation and checks nothing
# unless a checker is attached, so without this a vendor's "format" would silently reject nothing.
# Only checkers that cost no more than the length of their input are listed: "regex" is left out
# because it would compile caller input with Python's backtracking engine, which is exactly the
# cost the isolation exists to bound, not something this module tries to keep from happening, and
# "idn-hostname" because its cost lives in a third party library. Any other format stays an
# annotation, which is what JSON Schema says an unknown format is.
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


class InvalidArgumentsError(Exception):
    """Raised when the caller's arguments are themselves at fault, not the function's schema.

    Covers arguments that are not valid JSON (including a number too large for json.loads to
    parse) and arguments nested past MAX_DOCUMENT_DEPTH. Kept distinct from
    UnsupportedSchemaError, which is about the schema, so that a caller's own mistake is not
    reported as the function owner's schema being broken.
    """


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


def _schema_shape_error(schema: Any) -> str | None:
    """The rejection message when ``schema`` is not an object or a boolean, else None.

    jsonschema's own entry points assume one or the other: ``validator_for`` tests
    ``"$schema" not in schema``, which raises TypeError on a JSON number or null, and nothing
    downstream catches it, so the request came out as a 500 instead of a rejection. Shared by both
    entry points below so the same shape gets the same message whichever one is checking it.
    """
    if isinstance(schema, (dict, bool)):
        return None
    return f"a JSON Schema must be an object or a boolean, not {type(schema).__name__}"


def _require_schema_shape(schema: Any) -> None:
    """Raise UnsupportedSchemaError when ``schema`` is not an object or a boolean."""
    error = _schema_shape_error(schema)
    if error is not None:
        raise UnsupportedSchemaError(error)


def _comparison_key(value: Any) -> Any:
    """Return a hashable key that collides exactly when JSON Schema considers two values equal.

    Mirrors the comparison jsonschema makes itself: ``True`` is not ``1``, ``1`` is ``1.0``, and
    arrays and objects compare by their contents.
    """
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        # 1 and 1.0 are the same JSON number. Collapsing an integral float onto the integer keeps
        # that true without going through float(), which would lose precision on large integers.
        return ("number", int(value) if isinstance(value, float) and value.is_integer() else value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, (list, tuple)):
        return ("array", tuple(_comparison_key(item) for item in value))
    if isinstance(value, dict):
        return ("object", frozenset((key, _comparison_key(item)) for key, item in value.items()))
    # None, and anything else json.loads cannot produce. Tagged so that None cannot collide with
    # the string "None", and by repr so that two equal values still give one key.
    return ("other", repr(value))


def _unique_items(validator, unique, instance, schema):  # pylint: disable=unused-argument
    """Single-pass replacement for the ``uniqueItems`` keyword.

    jsonschema compares the elements pairwise whenever they are not sortable, which any array of
    objects triggers, and that comparison lives in a private helper that never descends into a
    subschema: 4000 objects took about 8 seconds while the isolation's default CPU budget would
    refuse them outright. Hashing a canonical form of each element answers the same question in
    one pass.
    """
    if not unique or not validator.is_type(instance, "array"):
        return
    seen = set()
    for item in instance:
        key = _comparison_key(item)
        if key in seen:
            yield jsonschema.ValidationError(f"{instance!r} has non-unique elements")
            return
        seen.add(key)


def _validator(schema: Any):
    """Build a jsonschema validator for ``schema``, with ``uniqueItems`` replaced.

    Everything else is the stock validator: ``pattern`` matches with Python's backtracking ``re``,
    and the isolation this runs inside bounds that cost. ``uniqueItems`` is the one keyword this
    module still replaces instead of leaving for the isolation to bound, because its cost lives in
    a private helper that never descends into a subschema (see ``_unique_items``).
    """
    base = jsonschema.validators.validator_for(schema)
    with_fast_unique_items = jsonschema.validators.extend(base, {"uniqueItems": _unique_items})
    return with_fast_unique_items(schema, registry=_NO_EXTERNAL_REFS, format_checker=_FORMAT_CHECKER)


# Keywords whose value is instance data rather than a subschema, so a "$ref" key sitting inside one
# is an ordinary object key that jsonschema never resolves.
_LITERAL_VALUE_KEYWORDS = frozenset({"const", "default", "enum", "examples"})

# Keywords whose value is a map from arbitrary names to schemas. The names are the schema author's
# to choose, so they can collide with any keyword above, which is why the walks descend through the
# schemas such a map holds rather than through the map itself. "dependencies" is the draft-07 form
# and may map a name to a list of property names instead of to a schema; walking one of those finds
# nothing, which is the right answer for it.
_SCHEMA_MAP_KEYWORDS = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "dependencies"}
)


def _schema_children(node: dict) -> Any:
    """Yield the values of ``node`` that JSON Schema evaluates as schemas.

    The reference walks below need this because a document holds two kinds of nested value and a
    "$ref" key means something only in one of them. Treating every nested dict as a schema refused
    a function whose schema pins a default or const object with a "$ref" key, wrongly reporting it
    as a reference that does not resolve or as an external reference.

    Skipping those keywords is not enough on its own, though, because a property may be named
    anything, "const" included. So for the keywords whose value is a map from arbitrary names to
    schemas, this yields the schemas rather than the map, and the names are never read as keywords.
    That keeps a reference under a property named like a keyword findable.
    """
    for keyword, value in node.items():
        if keyword in _LITERAL_VALUE_KEYWORDS:
            continue
        if keyword in _SCHEMA_MAP_KEYWORDS and isinstance(value, dict):
            yield from value.values()
        else:
            yield value


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
        for value in _schema_children(node):
            found = find_external_ref(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_external_ref(value)
            if found is not None:
                return found
    return None


def _pointer_resolves(root: Any, ref: str) -> bool:
    """Whether the JSON Pointer fragment of same-document reference ``ref`` names something in
    ``root``. ``ref`` is a "#" ("points at the whole document") or a "#/..." string.

    Only ever called with a ``ref`` whose fragment is actually a JSON Pointer: the caller,
    ``find_unresolvable_ref``, filters out plain-name anchor fragments before reaching here.
    """
    fragment = ref[1:]
    if fragment.startswith("/"):
        fragment = fragment[1:]
    node = root
    if not fragment:
        return True
    # A fragment is part of a URI and therefore percent-encoded, and referencing decodes the whole
    # fragment before splitting it, as ``unquote(pointer[1:]).split("/")`` in ``referencing._core``.
    # Decoding in that same order is what makes this agree with the library. Skipping it refused a
    # legitimate schema at upload: a "$defs" name holding a space is referenced as "#/$defs/a%20b"
    # by anything that builds the reference as a URI, and that pointer named nothing here while
    # jsonschema resolved it and enforced the subschema it names.
    for raw_segment in unquote(fragment).split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if segment not in node:
                return False
            node = node[segment]
        elif isinstance(node, list):
            try:
                index = int(segment)
            except ValueError:
                return False
            if not 0 <= index < len(node):
                return False
            node = node[index]
        else:
            return False
    return True


def _holds_subresource(node: Any) -> bool:
    """Whether any schema strictly below ``node`` declares its own "$id".

    An "$id" below the top level starts a separate resource, and a "#/..." pointer written inside
    that resource is resolved against the resource, not against the document this walk holds. The
    library does that in ``maybe_in_subresource``, called for every segment a pointer crosses.

    "$id" at the very top is not this case: it names the document itself, which is already the base
    every pointer resolves against, so it changes nothing here and is deliberately not counted.
    """
    if isinstance(node, dict):
        if isinstance(node.get("$id"), str):
            return True
        return any(_holds_subresource(value) for value in _schema_children(node))
    if isinstance(node, list):
        return any(_holds_subresource(value) for value in node)
    return False


def find_unresolvable_ref(schema: Any, root: Any = None) -> str | None:
    """Return the first same-document reference in ``schema`` that names nothing.

    A trial validation against an empty instance (see ``check_uploaded_schema_in_isolation``)
    catches a broken reference at the schema's root, because a top level "$ref" is resolved
    against every instance regardless of its shape. It does not catch one nested inside
    "properties" or "items": jsonschema never descends into either without an instance that has
    that property or is a non-empty array, so a broken pointer sitting there is never touched.
    Measured: the same broken reference that raises when placed at the root raises nothing when
    moved under "properties.x" or "items".

    This walks the whole document instead, independent of any instance, and resolves each
    "#/..." pointer with ``_pointer_resolves``. A reference to the document root or to an
    ancestor, such as ``{"properties": {"child": {"$ref": "#"}}}``, always resolves: that pointer
    names the document itself, which exists, so the ordinary way to describe a recursive
    structure is never rejected here. Only a pointer naming a location that is not there is
    unresolvable.

    A fragment after "#" is not always a JSON Pointer. "#" and "#/..." are; a plain name such as
    "#itemAnchor" is not, it is an anchor, set by ``$anchor``, ``$dynamicAnchor``, or an old-style
    ``$id: "#name"``, and jsonschema resolves it against its own anchor table, built while it
    compiles the schema, not by walking the document structure. This function does not build that
    table: doing so would mean reimplementing the part of jsonschema that already does this
    correctly, which is exactly the road that made an earlier version of this check reject
    legitimate schemas (recursive and extensible ones, which is precisely where the specification
    recommends anchors) outright, while only avoiding a false accept, in the ``$dynamicRef`` case,
    by coincidence, when an anchor name happened to collide with a literal top-level key. So a
    plain-name fragment is skipped here rather than resolved or rejected. That is not a gap this
    function leaves open: the trial validation above already catches the infinite-recursion case,
    and a reference to an anchor that genuinely does not exist surfaces at run time as
    jsonschema's own ``Unresolvable``, which ``work()`` below already turns into a plain 400.
    Do not "complete" this by adding anchor resolution.

    A nested "$id" is skipped for the same reason as an anchor, and the whole document is skipped
    rather than the one reference: an "$id" below the top level starts a separate resource, and
    every pointer written inside it resolves against that resource instead of against this
    document, so a pointer naming nothing here may still name something where the library looks.
    Which references are affected cannot be told apart without tracking the base URI down the walk,
    which is the anchor table's mistake in another form, so the check steps aside for the document.
    That is a false accept at worst, and the trial validation plus jsonschema's own ``Unresolvable``
    at run time both still apply. It was a false reject before: a "$defs" entry carrying its own
    "$id" and referring to its own inner "$defs" was refused at upload while jsonschema resolved it
    and enforced the subschema it names.

    External references are a separate, cheaper check (``find_external_ref``), and are assumed
    already rejected by the time this runs.

    Recursive on purpose, unlike the cheap walks above: it only ever runs inside the isolation,
    where a document deep enough to exhaust the stack costs a rejection rather than a failed
    request.
    """
    if root is None:
        root = schema
        if _holds_subresource(schema):
            return None
    if isinstance(schema, dict):
        for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
            ref = schema.get(keyword)
            if not isinstance(ref, str) or not ref.startswith("#"):
                continue
            fragment = ref[1:]
            if fragment and not fragment.startswith("/"):
                continue  # plain-name anchor, not a JSON Pointer; see docstring above
            if not _pointer_resolves(root, ref):
                return ref
        for value in _schema_children(schema):
            found = find_unresolvable_ref(value, root)
            if found is not None:
                return found
    elif isinstance(schema, list):
        for value in schema:
            found = find_unresolvable_ref(value, root)
            if found is not None:
                return found
    return None


# Longest excerpt of either caller-controlled value a validation message quotes: what the schema
# required, and what was rejected. A validation message carries both, and both are as large as
# whoever wrote them made them, so the figure is a budget shared between the two rather than a
# separate allowance each: two of these plus the fixed wording still has to stay clear of
# validate_arguments.MAX_MESSAGE_LENGTH, or the truncation up there would cut off the very part of
# the message this function exists to keep.
MAX_EXCERPT_LENGTH = 150


def _validation_message(exc: jsonschema.ValidationError) -> str:
    """Build a rejection message from ``exc``'s own fields instead of using ``exc.message``.

    jsonschema builds ``exc.message`` as ``f"{instance!r} <reason>"``: the rejected value first,
    the reason ("is not of type 'integer'", "is a required property", ...) last. Truncating that
    to a fixed length, as the caller of this function does for defence in depth, keeps whatever is
    at the front and drops the rest, so a rejected value at or past that length, such as a 39 KB
    base64 encoded circuit, came back with 500 characters of base64 and no reason at all.

    ``exc.validator`` (the keyword that failed, e.g. "type") and ``exc.validator_value`` (what the
    schema required for it, e.g. "integer") are ``exc``'s own fields and do not grow with the size
    of the instance, so building the message from them keeps the reason present no matter how
    large the rejected value is. This must run here, inside the child, while ``exc`` is still the
    real ``jsonschema.ValidationError`` jsonschema raised: only ``message`` and ``path`` cross the
    isolation boundary (see ``work()`` below), so by the time the caller in
    ``validate_arguments.py`` sees a ``jsonschema.ValidationError``, it has been reconstructed from
    just those two fields and ``validator``/``validator_value`` read back as "<unset>".

    Both quoted values are bounded, not just the rejected one. ``validator_value`` is independent of
    the instance, which is the case this function was written for, but it is a piece of the schema,
    so it grows with the schema instead: for "enum" it is every allowed value, for "anyOf" or
    "properties" a whole subschema, up to MAX_SCHEMA_LENGTH. Bounding only the instance therefore
    reintroduced the same failure with the schema in the payload's place, and an enum of a few
    hundred options came back as the truncation limit's worth of enum with the rejected value gone.
    A boolean schema has neither field. jsonschema raises for ``False`` with ``validator`` and
    ``validator_value`` both left as None, so building the message from them produced "'None'
    validation failed, schema requires None", naming no keyword and no requirement, and dropped the
    library's own "False schema does not allow 1". That schema is the one this feature made
    meaningful, since ``false`` used to disable validation and now rejects every instance, so the
    message a caller gets for it is worth spelling out rather than leaving as two Nones.
    """
    if exc.validator is None:
        return f"the schema rejects every value: rejected value {_excerpt(exc.instance)}"
    return (
        f"'{exc.validator}' validation failed, schema requires {_excerpt(exc.validator_value)}"
        f": rejected value {_excerpt(exc.instance)}"
    )


def _excerpt(value: Any) -> str:
    """``repr(value)``, cut to MAX_EXCERPT_LENGTH and marked as cut when it was."""
    text = repr(value)
    if len(text) > MAX_EXCERPT_LENGTH:
        return f"{text[:MAX_EXCERPT_LENGTH]}... (value truncated)"
    return text


def validate_arguments_in_isolation(schema: Any, arguments_str: str) -> None:
    """Parse ``arguments_str`` and validate it against ``schema`` in a child with hard limits.

    The caller applies the text limits on the schema first. Parsing the arguments happens inside
    the child on purpose: json.loads raises RecursionError on a few kilobytes of nesting and
    ValueError on an integer with more than 4300 digits, both from caller input, and outside the
    isolation each of those came out of the request as a 500.

    Raises:
        InvalidArgumentsError: if the arguments are not valid JSON or are nested too deep. This is
            the caller's mistake, not the function owner's schema.
        UnsupportedSchemaError: if the schema itself cannot be evaluated, or a limit fired while
            validating against it.
        jsonschema.ValidationError: if the arguments do not match the schema, with ``path`` set.
    """
    _require_schema_shape(schema)

    def work():
        try:
            arguments = json.loads(arguments_str)
        except (json.JSONDecodeError, ValueError, RecursionError) as exc:
            return {"invalid_arguments": f"arguments is not valid JSON: {exc}"}
        if exceeds_max_depth(arguments):
            return {"invalid_arguments": f"arguments are nested more than {MAX_DOCUMENT_DEPTH} levels deep"}
        try:
            _validator(schema).validate(arguments)
            return {"valid": True}
        except jsonschema.ValidationError as exc:
            return {"valid": False, "message": _validation_message(exc), "path": list(exc.path)}
        except MemoryError:
            # Left to the blanket handler below, this reads as {"unusable": "MemoryError: "}: an
            # empty message, because MemoryError carries no text of its own. Re-raising instead lets
            # _run_child's own except MemoryError (api/domain/isolated.py) name the limit that fired,
            # which is the whole reason that handler exists.
            raise
        except Exception as exc:  # pylint: disable=broad-except
            # SchemaError, Unresolvable, RecursionError, UnknownType, and the TypeError and
            # AttributeError a malformed keyword raises. Every one of these used to be a 500.
            return {"unusable": f"{type(exc).__name__}: {exc}"}

    answer = _answer_from_child(work)
    if "invalid_arguments" in answer:
        raise InvalidArgumentsError(answer["invalid_arguments"])
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
        shape_error = _schema_shape_error(schema)
        if shape_error is not None:
            return {"error": shape_error}
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
        unresolvable_ref = find_unresolvable_ref(schema)
        if unresolvable_ref is not None:
            return {"error": f"it contains a reference that does not resolve: '{unresolvable_ref}'"}
        try:
            jsonschema.validators.validator_for(schema).check_schema(schema)
        except jsonschema.SchemaError as exc:
            return {"error": f"it is not a valid JSON Schema: {exc.message}"}
        except MemoryError:
            # See the matching comment in validate_arguments_in_isolation.work(): left to the
            # blanket handler below, this reads as an empty "MemoryError:" message instead of
            # letting isolated.py's own except MemoryError name the limit that fired.
            raise
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"it cannot be used ({type(exc).__name__}: {exc})"}
        # check_schema only verifies the document is a valid JSON Schema; it never evaluates it.
        # {"$ref": "#"} and {"$ref": "#/$defs/nope"} both passed check_schema and then failed every
        # single run of the function: the first recurses without end, the second names nothing.
        # find_unresolvable_ref just refused the second kind wherever it can be found by walking
        # the document; this catches the first kind and anything else only evaluation reveals, by
        # actually trying to validate with it. The instance does not matter, since nothing here
        # cares whether it matches: a ValidationError is the expected, uninteresting outcome, and
        # is not proof the schema is usable in general, only that this one instance was evaluated
        # against it without the process itself falling over.
        try:
            _validator(schema).validate({})
        except jsonschema.ValidationError:
            pass
        except MemoryError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            return {"error": f"it cannot be used ({type(exc).__name__}: {exc})"}
        return {"ok": True}

    answer = _answer_from_child(work)
    if "error" in answer:
        raise UnsupportedSchemaError(answer["error"])


def _answer_from_child(work) -> Any:
    """Run ``work`` in the isolation, turning a limit being hit into UnsupportedSchemaError."""
    try:
        return run_isolated(work, memory_mb=_memory_limit_mb(), cpu_seconds=_cpu_limit_seconds())
    except IsolationError as exc:
        raise UnsupportedSchemaError(exc.reason) from exc
