# Argument validation

This document describes how a Qiskit Function declares the arguments it accepts, and how the gateway validates
submitted arguments against that declaration before any compute is used.

Without it, a function that receives bad input fails mid-execution: the user waits through queue time and container
startup only to get a runtime error. That is a poor experience, and it is not only an experience problem, because a job
that starts and then fails on its own input has already consumed billable compute, which with the billing service can
trigger refund operations. Vendors can now attach a [JSON Schema](https://json-schema.org/) to their function, and the
gateway rejects mismatching arguments at the API level, immediately and with a clear message.

The feature is opt-in and backwards compatible: a function without a schema is never validated.

Out of scope: argument errors that cannot be expressed as a JSON Schema constraint. A schema catches shape, type and
range, not "these two parameters are individually valid but contradict each other" or anything that depends on the
state of a backend. Those still surface at runtime.

## Where the schema lives

`Program.arguments_schema` (`gateway/core/models.py`), added by migration `0056_program_arguments_schema`:

```python
arguments_schema = models.TextField(null=True, blank=True, default="{}")
```

It stores the schema as **text**, not as a JSON column. The field is nullable, so the migration is rollback
compatible: old code inserting a `Program` row leaves the column `NULL`, and the read path treats `NULL` the same as
"no schema".

Both `NULL`/empty and `"{}"` mean *no validation*. There is no separate "validation enabled" flag.

Note that `{}` is the only object that means "no schema". The schema `false` is a valid JSON Schema that rejects every
instance, so it is honoured as written rather than treated as "nothing to do".

## Declaring a schema

The schema is set through the existing upload endpoint, `POST /api/v1/programs/upload/`, as a regular form field
alongside `title`, `dependencies`, `env_vars` and the rest. It is metadata, not a file upload (the only file in that
request is the `artifact` tarball).

`ProgramSerializer.validate_arguments_schema` (`gateway/api/v1/views/programs/upload.py`) rejects at upload anything
the gateway would not be able to evaluate later. It checks, in this order:

1. The value is no longer than `MAX_SCHEMA_LENGTH`, checked before anything is forked.
2. Inside a forked child (`check_uploaded_schema_in_isolation`, see [What a schema may
   contain](#what-a-schema-may-contain)): the value parses as JSON and is an object or a boolean; it does not nest
   deeper than `MAX_DOCUMENT_DEPTH` or contain more than `MAX_SCHEMA_NODES` subschemas; no reference points outside
   the document, checking `$ref`, `$dynamicRef` and `$recursiveRef` (`find_external_ref`); every same-document
   reference resolves to something that actually exists in the document (`find_unresolvable_ref`); the document is a
   valid JSON Schema for its own dialect, via `validator_for(schema).check_schema(schema)`; and, last, the schema is
   tried once against a trial instance, an empty object, discarding whether it matches and only watching for
   anything other than the ordinary `ValidationError` that comparison can raise.

The point of doing all of this at upload time is *who gets the error*. The person who can fix a broken schema is the
one uploading it, so a schema the upload checks know how to catch is refused there, with a `400` naming the problem,
instead of turning every later run of that function into a failure that the caller can do nothing about. It is not a
promise that every unusable schema is caught this way: `check_schema` verifies the document is syntactically a valid
JSON Schema, never that evaluating it terminates, and the trial instance is a single fixed shape, an empty object,
so it only exercises the parts of the schema an empty object happens to reach (a broken reference at the schema's
root, but not one describing a deeply nested test that requires other test data). `find_unresolvable_ref` closes the
gap the trial instance leaves for a broken reference specifically, by walking the whole document instead of only
what one instance touches, but no equivalent walk exists for every other way evaluation can go wrong. The upload
checks are quality of service, catching the cases known to leave a function permanently unusable so the error reaches
whoever can fix it; the isolation described below is the actual protection, and it bounds whatever the upload checks
miss into a plain `400` at run time instead of an unbounded cost or a `500`.

### Re-upload preserves the schema

`UploadFunctionUseCase._update` only writes `arguments_schema` when the field is present in the request, using `None`
in `UploadFunctionInput` as the "not sent" sentinel:

```python
if data.arguments_schema is not None:
    instance.arguments_schema = data.arguments_schema
```

So a vendor can update a schema by sending just the title plus `arguments_schema`, and re-uploading code without the
field does not wipe an existing schema. The same preserve-when-omitted rule applies to the other optional fields
(`runner`, `dependencies`, `env_vars`, `entrypoint`, `artifact`, `image`, `description`, `version`).

Because omitting the field means "leave it alone", removing a schema is done by sending an empty one, `{}`, which is
the same value as never having had one. From the SDK that is `arguments_schema={}`, since `None` is what marks the
field as not sent:

```python
function.arguments_schema = {}
client.upload(function)   # the function stops validating its arguments
```

## What a schema may contain

Both sides of this validation are untrusted input that the gateway evaluates **in the request thread**: the schema
comes from whoever owns the function, the instance from whoever runs it. A JSON Schema `pattern` is a regular
expression applied to caller input, and Python's backtracking engine makes that exponential in the length of the
input, so a request body of under 100 bytes could otherwise keep a worker busy for hours. `jsonschema` also spends
unbounded cost in a private helper behind `uniqueItems` that never descends into a subschema, so a rule that only
watches recursion cannot see it either.

An earlier version of this feature tried to bound that cost from inside `jsonschema` itself: a validator subclass
counting subschema visits, a wall clock deadline, `pattern` matched with a non-backtracking engine, a replaced
`uniqueItems`, and a list of keywords refused outright because their cost lived in private helpers. Three
rounds of review found four separate ways past that scheme: keywords whose cost lives in private module level helpers
no subclass can reach, a `$schema` below the top level restoring the stock backtracking validator class on a
reference, the size of a compiled regex program, and memory, which nothing in that scheme bounded at all. `jsonschema`
also warns that subclassing its validator classes is not part of its public API and will become an error in a future
release, so a fix that depended on it would need redoing regardless.

Validation now runs in a forked child (`gateway/api/domain/isolated.py`), bounded from outside `jsonschema` instead of
from within it. The child gets a CPU limit and an address space limit before it does anything else: whatever the
validation does inside, it either finishes within those limits or the child dies, and the parent turns that into a
rejection rather than an occupied worker. Measured by execution: `RLIMIT_CPU` kills a runaway `pattern` match at 1.00s
with `SIGXCPU`, and `RLIMIT_AS` turns a 1 GB allocation into a catchable `MemoryError` at 0.38s on Linux.

`RLIMIT_AS` does not fire on macOS. The limit is computed at runtime from the process's own address space, read from
`/proc/self/status`. That file does not exist on macOS, so the read fails, the computed size comes back as 0, and the
limit is skipped rather than set to a wrong value. The CPU limit is unaffected and fires the same way on both
platforms, so this is the one part of the protection that degrades in development and applies in production: a schema
that only spends memory rather than CPU can validate without complaint on a laptop and still be refused once deployed.

The memory margin above that base is `settings.ARGUMENTS_SCHEMA_MEMORY_LIMIT_MB` (`gateway/main/settings.py`, default
128), read by `api/domain/arguments_schema.py` and passed into `run_isolated`, which itself only knows a plain numeric
default: the isolation mechanism stays free of Django so it can be reused outside a web request. Measured in a
container at the pod's real limits (2 Gi memory, 3 CPU, `gunicorn --workers=2 --threads=1`): a 512 MB margin let a
4 KB schema plus 1 MB of arguments drive one child to 526 MB, and two concurrent such requests, exactly the worker x
thread concurrency, added about 960 MB to the cgroup and got a process OOM-killed by the kernel. Every legitimate
shape tested, including a 1 MB batch of encoded circuits and 4000 objects under `uniqueItems`, passes at 64 MB.
Because the setting is a way to weaken this by configuration, the value read from it is clamped to 64-256 MB before
reaching the child, rather than used as given.

Inside the child, `jsonschema` runs unmodified, with one exception: `uniqueItems` is still replaced, by a single-pass
hash of a canonical form of each element, rather than being left for the isolation alone to bound. `jsonschema`
compares elements pairwise whenever they are not sortable, which any array of objects triggers, and that comparison
lives in a private helper that never descends into a subschema, so it pays its full quadratic cost within a single
CPU-second budget regardless: 1500 objects in 18 KB of JSON were refused for exceeding the CPU limit, where the
hash-based replacement answers in 0.011s. `pattern`, by contrast, is on the stock engine now, matched with Python's
ordinary backtracking `re` and left for the isolation to bound; `uniqueItems` is the one place where isolation can
only refuse the work rather than make it cheap.

Before any of this runs, text limits are applied to the schema, and to the arguments:

| Constant | Value | What it bounds |
|---|---|---|
| `MAX_SCHEMA_LENGTH` | 64 KB | How much combinatorial work a schema can spell out literally |
| `MAX_ARGUMENTS_LENGTH` | 1 MB | Keywords whose cost grows with the instance |
| `MAX_DOCUMENT_DEPTH` | 64 | Nesting of schema and arguments; CPython gives up near 180 |
| `MAX_SCHEMA_NODES` | 200 | Subschemas in the document, which bounds memory on every platform |

`MAX_SCHEMA_LENGTH` is checked before anything is forked, on both entry points. `MAX_ARGUMENTS_LENGTH` only applies on
`/run` and `/validate_arguments/`: upload has no arguments to bound, only a schema. Where `MAX_DOCUMENT_DEPTH` and
`MAX_SCHEMA_NODES` are checked on the schema differs by entry point: on `/run` and
`/validate_arguments/` (`validate_arguments_in_isolation`), the caller already holds the schema as a parsed object and
checks both before forking. At upload (`check_uploaded_schema_in_isolation`), the schema is still text when it
arrives, and parsing it is itself part of what has to be isolated, so `json.loads` and both checks run inside the
child instead. `MAX_DOCUMENT_DEPTH` on the arguments always runs inside the child, for the same reason: they are still
text outside it. An upload is refused outright if the schema contains more than 200 subschemas, the same
`MAX_SCHEMA_NODES` limit that a run-time check applies, because memory use there scales with the number of branches
times the size of the instance, which is the half of the memory protection that holds on every platform, including
where `RLIMIT_AS` does not fire.

**References are never retrieved.** The schema is evaluated against a `referencing.Registry` built with no retrieval
hook of its own, so a reference pointing outside the document raises `Unresolvable` instead of making the gateway
issue a request or read a file. Verified with a spy on `socket.connect`: no socket calls happen with this registry,
where `getaddrinfo` plus `connect` happen with `jsonschema`'s default one. The registry is not empty, despite having
no entries of its own: `jsonschema` does `SPECIFICATIONS.combine(registry)` internally, so the packaged metaschemas
still resolve. What it stops is going out to the network for anything else. Same-document references such as
`#/$defs/name` keep working normally. Upload rejects an external reference up front anyway, so this is the second
line of defence rather than the first.

## Reading a schema back

`arguments_schema` is included in the output of both read endpoints, so a schema is not write-only:

| Endpoint | Serializer |
|---|---|
| `GET /api/v1/programs/get_by_title/<title>/` | `api/v1/views/programs/get_by_title.py` |
| `GET /api/v1/programs/` | `api/v1/views/programs/list.py` |

This lets a user inspect the arguments a function expects even when they did not upload it themselves. The value comes
back as the stored **string**, so the client SDK decodes it into a dict (see [Client SDK](#client-sdk)).

## Arguments are validated in encoded form

This is the one thing most likely to surprise a schema author, so it is worth stating plainly: **the schema is applied
to the arguments as the SDK encodes them, not as they look in Python.**

The client serializes arguments with `QiskitObjectsEncoder` (`client/qiskit_serverless/serializers/program_serializers.py`),
which extends `RuntimeEncoder` from `qiskit-ibm-runtime`. Qiskit objects become tagged objects with `__type__` and
`__value__` keys. Both `run` and `validate_arguments` use the same encoder, so a pre-flight check sees exactly what a
real run would send.

What arrives at the gateway, verified against the encoder:

| Python argument | JSON the schema sees |
|---|---|
| `QuantumCircuit` | `{"__type__": "QuantumCircuit", "__value__": "<base64 QPY>"}` |
| `numpy.ndarray` | `{"__type__": "ndarray", "__value__": "<base64>"}` |
| `complex(1, 2)` | `{"__type__": "complex", "__value__": [1.0, 2.0]}` |
| `1024`, `"text"`, `True`, lists and dicts of those | unchanged |

So the natural looking schema is wrong for anything but plain JSON types. Describing a numpy array as
`{"arr": {"type": "array"}}` rejects every legitimate call, because an `ndarray` arrives as an *object*. A complex
number, on the other hand, really is an array of two numbers, but nested inside the tagged object.

To constrain a circuit argument, describe the encoded object:

```json
{
  "type": "object",
  "properties": {
    "circuit": {
      "type": "object",
      "required": ["__type__", "__value__"],
      "properties": {
        "__type__": {"const": "QuantumCircuit"},
        "__value__": {"type": "string"}
      }
    },
    "shots": {"type": "integer", "minimum": 1}
  },
  "required": ["circuit"]
}
```

The practical advice for a vendor is to validate the plain arguments (counts, names, options, flags) and to check only
the `__type__` tag of the Qiskit ones, since the payload itself is opaque base64.

One consequence of encoding worth knowing: `MAX_ARGUMENTS_LENGTH` applies to the encoded text, which is much larger
than the same arguments look in a notebook. A random 100 qubit, depth 100 circuit encodes to about 39 KB, so the 1 MB
limit leaves room for a batch of roughly twenty five of them. It is set there deliberately: an earlier draft used 100000
characters, which a batch of three such circuits already exceeded, and a limit that rejects ordinary work is worse than
no limit, since the cost it was guarding against is bounded by other means. This limit only applies to functions that
**declare a schema**: the length check runs after the "no schema, nothing to do" short-circuit, so functions without one
are unaffected.

## Validating arguments

Validation lives in one place, `gateway/api/use_cases/programs/validate_arguments.py`, and is reached two ways.

The module exposes a plain function for callers that already resolved the function, and a use case class for callers
that only have a title:

```python
def validate_arguments(program: Function, arguments_str: str) -> None:
    """No-op if schema is empty. Raises InvalidArgumentsException otherwise."""


class ValidateArgumentsUseCase:
    def execute(self, user, accessible_functions, title, provider_name, arguments) -> None:
        """Resolves the function (raising FunctionNotFoundException), then validates."""
```

`validate_arguments` short-circuits when there is nothing to validate, applies the length limit to the schema and to
the arguments and the depth and node count limits to the schema, then hands the actual work to
`validate_arguments_in_isolation` (`gateway/api/domain/arguments_schema.py`, dependency `jsonschema>=4.26.0,<5` in
`gateway/requirements.txt`), which runs inside the forked child described in [What a schema may
contain](#what-a-schema-may-contain):

```python
schema_str = program.arguments_schema
if not schema_str or schema_str == "{}":
    return
# ... length limit on schema_str and arguments_str, json.loads of the schema, depth and node count limits on it ...
try:
    validate_arguments_in_isolation(schema, arguments_str or "{}")
except InvalidArgumentsError as exc:
    ...
except UnsupportedSchemaError as exc:
    ...
except jsonschema.ValidationError as exc:
    ...
```

Every one of those becomes an `InvalidArgumentsException`, so a schema problem is a `400` and never a `500`.
`InvalidArgumentsError` covers the caller's own mistakes, caught inside the child: arguments that are not valid JSON,
or arguments nested past `MAX_DOCUMENT_DEPTH`. `UnsupportedSchemaError` covers everything wrong with the schema
itself, including a self-referencing document (`{"$ref": "#"}`, 13 characters) that recurses without end while being
evaluated: nothing catches that particular `RecursionError` by name, so the child's generic handler turns it into a
rejection instead of letting it escape. `RecursionError` is still caught by name in three other places, all around
`json.loads` rather than around evaluating a schema: parsing the arguments and parsing the schema, both inside the
child, and parsing the schema in the use case before anything is forked.

Messages are truncated at `MAX_MESSAGE_LENGTH` (500 characters). `jsonschema` builds its messages with
`repr(instance)`, so without that a rejected payload came back to the caller in full.

The metaschema check itself only runs once, at upload time (`check_uploaded_schema_in_isolation`), never again on a
later run: it used to run on every request too, which cost 89 ms for a 63 KB schema and put a ceiling of about 22
requests a second on the gateway.

### On `/run`

`RunFunctionUseCase.execute` calls `validate_arguments(function, data.arguments)` **before** creating the `JobConfig`
and `Job` rows, and after the function has been resolved, permission-checked, and the active-job limit applied. A
rejected payload therefore leaves no orphaned rows behind and consumes no compute.

Order inside the use case:

1. Resolve the function → `FunctionNotFoundException` (404)
2. Function disabled → `FunctionDisabledException` (423)
3. Active job limit → `ActiveJobLimitExceeded` (429)
4. Fleets function missing a Code Engine project → DRF `ValidationError` (400)
5. **Validate arguments** → `InvalidArgumentsException` (400)
6. Create `JobConfig` and `Job`

### On `/validate_arguments/`

`POST /api/v1/programs/validate_arguments/` validates without submitting anything. It is useful for vendors testing a
schema and for users checking inputs before paying for a run.

Request body:

| Field | Required | Notes |
|---|---|---|
| `title` | yes | Accepts the `provider/title` convention; sanitized in the serializer |
| `arguments` | yes | JSON string |
| `provider` | no | Alternative to putting the provider in `title` |

A provider function can be addressed either way: as `title="acme/my-function"` or as `title="my-function"` plus
`provider="acme"`. The convention lives in one place, `parse_title_and_provider` in `api/utils.py`, shared by this
endpoint, `/get_by_title` and `/upload`. It sanitizes both values and rejects the two malformed cases: a provider given
in both places at once, and a title with more than one slash. Rejecting is safe precisely because `/upload` is what
creates functions, so a title `/upload` refuses cannot belong to an existing one, and a clear 400 beats a puzzling 404.

`/run` is the one endpoint that still does not apply the convention, so there a provider function must be addressed
with `provider` as its own field. The client SDK always separates the two in `QiskitFunction.__post_init__`, so SDK
callers never notice; direct API callers do.

The view (`api/v1/views/programs/validate_arguments.py`) only parses and sanitizes input, then hands off to
`ValidateArgumentsUseCase`. Function resolution and permissions match `/run`: `PLATFORM_PERMISSION_RUN` /
`RUN_PROGRAM_PERMISSION` for provider functions, `JobAccessPolicies.can_create` for a user's own functions. A function
the caller cannot reach is reported as not found, never as a permission error, so the endpoint does not leak the
existence of other vendors' functions.

There is one deliberate difference from `/run`: **this endpoint does not check `function.disabled`**, so validating
against a disabled function succeeds where running it would give a 423. `disabled` is an availability flag rather than
a permission, and a disabled function's schema is already readable through `get_by_title` and `list`, so refusing here
would remove something useful (preparing arguments while a function is temporarily unavailable) without protecting
anything. The trade-off is that a successful validation is not a promise that `/run` will accept the job.

Success is `200 {"valid": true}`.

## Error responses

Failures raise a domain exception; the view never builds an error `Response` by hand.
`InvalidArgumentsException` (`api/domain/exceptions/invalid_arguments_exception.py`) carries both the message and the
path to the offending field:

```python
class InvalidArgumentsException(Exception):
    def __init__(self, message: str, path: list = None):
        self.message = message
        self.path = path if path is not None else []
```

`api/v1/exception_handler.py` maps it centrally:

```python
except InvalidArgumentsException as error:
    return Response(
        {"message": error.message, "path": error.path},
        status=status.HTTP_400_BAD_REQUEST,
    )
```

Keeping `path` is the reason for a dedicated exception rather than reusing DRF's `ValidationError`: the generic handler
flattens a `ValidationError` to a single message, which would lose *which* field was wrong.

At upload, a schema the gateway cannot evaluate is a DRF `ValidationError` and therefore a `400` with a flat message.
At validation time, everything below is an `InvalidArgumentsException`, so a broken schema never becomes a `500`:

| Situation | Status | Body |
|---|---|---|
| Arguments violate the schema | 400 | `{"message": "...", "path": [...]}` |
| `arguments` is not valid JSON | 400 | `{"message": "arguments is not valid JSON: ...", "path": []}` |
| `arguments` longer than `MAX_ARGUMENTS_LENGTH` or nested past `MAX_DOCUMENT_DEPTH` | 400 | `{"message": "...", "path": []}` |
| Schema cannot be evaluated: an isolation limit was hit, a reference is unresolvable, evaluating it recurses without end, or it is not a valid JSON Schema (including not being an object or a boolean) | 400 | `{"message": "the function arguments schema cannot be used: ...", "path": []}` |
| Function missing or not accessible | 404 | `{"message": "..."}` |
| `arguments_schema` rejected at upload | 400 | `{"message": "arguments_schema ..."}` |

## Client SDK

`QiskitFunction.arguments_schema` (`client/qiskit_serverless/core/function.py`) is a **dict**, not a JSON string:

```python
arguments_schema: Optional[Dict[str, Any]] = None
```

Declare it at upload time:

```python
function = QiskitFunction(
    title="my-function",
    entrypoint="main.py",
    working_dir="./src",
    arguments_schema={
        "type": "object",
        "required": ["shots"],
        "properties": {"shots": {"type": "integer"}},
    },
)
runnable = client.upload(function)
```

It is `json.dumps`'d into the upload payload by both `_upload_with_docker_image` and `_upload_with_artifact`, and is
omitted from the request entirely when unset, so the gateway's preserve-on-re-upload rule applies.

Check arguments without running:

```python
runnable.validate_arguments({"shots": 1024})   # {"valid": True}, or raises QiskitServerlessException
```

`RunnableQiskitFunction.validate_arguments` delegates to `ServerlessClient.validate_arguments`, which POSTs to the
endpoint. Errors surface as `QiskitServerlessException` through the usual `safe_json_request_as_dict` path, so the
client never swallows a gateway rejection.

Because the gateway returns the schema as text, `from_json` decodes it back into a dict (`_decode_fields`), normalizing
the stored `"{}"` default to `None` so `if function.arguments_schema:` behaves as expected.

## Design decisions

- **Validation is server-side only.** The schema is authoritative on the gateway. The client does not validate locally,
  so an outdated SDK cannot let bad arguments through, and a schema change takes effect without a client release. The
  cost is a network round-trip for `validate_arguments()`.
- **Validation runs before any row is written.** Placing it after permission and quota checks, but before `JobConfig`
  and `Job` creation, means an invalid payload never leaves partial state, and a caller without access gets 404 rather
  than a schema error that would confirm the function exists.
- **No schema means no validation.** Rather than a separate toggle, an absent or empty schema is the off switch. Every
  function that existed before this feature keeps working untouched.
- **The schema is stored as text.** It is round-tripped verbatim rather than normalized through a JSON column, so what a
  vendor uploads is what they read back.
- **A dedicated exception instead of DRF's `ValidationError`,** so the 400 response can keep the `path` to the offending
  field instead of collapsing to one flat message.
- **A schema is refused at upload when the gateway knows how, not at run time.** The cost of evaluating a schema is a
  property of the schema, so the check belongs where the author can still act on the error, and upload does refuse
  every case it knows about: not just a document that fails its own metaschema, but one that would recurse without
  end (a trial validation against an empty instance) or reference something that is not there (`find_unresolvable_ref`
  walking the whole document, since the trial instance alone only reaches what an empty object touches). What upload
  does not do is guarantee completeness: those two checks catch the ways this has been seen to leave a function
  permanently unusable, not every way a schema can be unusable, and nothing rechecks the schema on `/run` because
  doing so would just repeat the identical bounded cost, not add coverage. `MAX_DOCUMENT_DEPTH` and `MAX_SCHEMA_NODES`
  are the exception: they are rechecked at run time, because a schema stored before either limit existed must not
  become a way around it. The upload checks are quality of service, so the error reaches whoever can fix it instead
  of every caller; the isolation is what actually keeps a schema the upload checks did not catch from costing more
  than a bounded amount, turning it into a plain `400` at run time instead of an unbounded cost or a `500`.
- **Cost is bounded by isolation, not by refusing keywords.** A forked child with a CPU limit and an address space
  limit bounds every keyword uniformly, including ones whose cost lives in private helpers a validator subclass could
  never reach. `uniqueItems` is the one keyword still replaced outright, not because isolation cannot bound it, but
  because paying the isolation's CPU budget just to be refused is a worse experience than a hash-based check that
  answers immediately.
