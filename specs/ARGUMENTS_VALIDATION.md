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
the gateway would not be able to evaluate later. It runs four checks, in this order:

1. The value parses as JSON.
2. No reference points outside the document, checking `$ref`, `$dynamicRef` and `$recursiveRef` (`_find_external_ref`).
3. `check_arguments_schema` (see [What a schema may contain](#what-a-schema-may-contain)).
4. The document is a valid JSON Schema for its own dialect, via `validator_for(schema).check_schema(schema)`.

The point of doing all of this at upload time is *who gets the error*. The person who can fix a broken schema is the
one uploading it, so a schema that cannot be used is refused there, with a `400` naming the problem, instead of
turning every later run of that function into a failure that the caller can do nothing about.

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
input, so a request body of under 100 bytes could otherwise keep a worker busy for hours.

No single limit bounds that cost, because `jsonschema` spends it in two different places. Most of it goes through
`descend`, which is a method and can therefore be counted. The rest is spent inside private module level helpers that
subclassing cannot reach (`uniq` behind `uniqueItems`, `find_evaluated_property_keys_by_schema` behind
`unevaluatedProperties`), and those do their work without descending even once, so a budget on subschemas is blind to
them. Hence a rule per place the cost can hide, all of them in `gateway/api/domain/arguments_schema.py`.

Bounding the input:

| Constant | Value | What it bounds |
|---|---|---|
| `MAX_SCHEMA_LENGTH` | 64 KB | How much combinatorial work (nested `anyOf` / `allOf`) a schema can spell out literally |
| `MAX_ARGUMENTS_LENGTH` | 100000 characters | Keywords whose cost grows with the instance. The ceiling otherwise was `DATA_UPLOAD_MAX_MEMORY_SIZE`, 2.5 MB by default |
| `MAX_DOCUMENT_DEPTH` | 64 | Nesting depth of the schema **and** of the arguments. `jsonschema` recurses once per level and CPython gives up at about 180 |

Bounding what the validation does:

| Constant | Value | What it bounds |
|---|---|---|
| `MAX_VALIDATION_STEPS` | 10000 | Subschemas one validation may visit. A realistic schema needs single digits |
| `MAX_VALIDATION_SECONDS` | 2.0 | Wall clock ceiling, checked on every descent. The backstop for a shape nobody enumerated |

Both are checked in `descend`, so they bound everything that recurses through it, and neither can interrupt a single
keyword that is already slow. That is what the next three rules are for:

- **`pattern` is matched with RE2** (`google-re2`), which never backtracks, so matching is linear in the length of the
  input. A pattern has to be valid in RE2 *and* in Python's `re`, because the metaschema checks it with `re`, so RE2
  extensions such as `\p{L}` are refused, with a message that says so.
- **`uniqueItems` is replaced** by a single-pass hash of a canonical form of each element. `jsonschema` compares the
  elements pairwise whenever they are not sortable, which any array of objects triggers, and that comparison never
  descends, so the step budget could not see it.
- **`patternProperties`, `unevaluatedProperties` and `unevaluatedItems` are refused** outright, because their cost
  lives in those private helpers rather than in a keyword, so it can neither be replaced nor counted. The error names
  the alternative to write instead.

Two more rules that are less obvious:

- **`$schema` is only accepted at the top level.** `jsonschema` picks the validator class from `$schema` for every
  subschema it descends into, so a nested one would switch back to a class that matches with Python's `re` and undo
  the RE2 rule.
- **`format` is asserted, but only for cheap checkers.** `jsonschema` treats `format` as an annotation and checks
  nothing unless a checker is attached, so a vendor writing `{"type": "string", "format": "email"}` used to get
  neither validation nor a warning. The asserted set is `date`, `email`, `idn-email`, `ipv4`, `ipv6` and `uuid`.
  `regex` is deliberately left out, since it would compile caller input with the very engine the RE2 rule exists to
  avoid, and any other format stays an annotation, which is what JSON Schema says an unknown format is.

The keyword scan (`check_arguments_schema`) walks **every** dict in the document, not only the schema positions, so a
refused keyword used as a property name or inside an `enum`, `const` or `default` value is refused too.
Over-approximating is the safe direction, since missing a position would mean missing the cost, and the error message
says as much so an author can tell the two cases apart.

**References are never retrieved.** The schema is evaluated against an empty `referencing.Registry`, which has no
retrieval hook, so a reference pointing outside the document raises `Unresolvable` instead of making the gateway issue
a request or read a file. Same-document references such as `#/$defs/name` keep working normally. Upload rejects an
external reference up front anyway, so the empty registry is the second line rather than the first.

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

One consequence of encoding worth knowing: `MAX_ARGUMENTS_LENGTH` applies to the encoded text. A single circuit is
small (a random 100 qubit, depth 100 circuit encodes to about 39 KB), but a batch of large circuits can exceed
100000 characters, and three of that size do. This limit only applies to functions that **declare a schema**: the
length check runs after the "no schema, nothing to do" short-circuit, so functions without one are unaffected.

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

`validate_arguments` short-circuits when there is nothing to validate, applies the length and depth limits, then hands
the actual work to the bounded validator (dependencies `jsonschema>=4.26.0,<5` and `google-re2>=1.1,<2` in
`gateway/requirements.txt`):

```python
schema_str = program.arguments_schema
if not schema_str or schema_str == "{}":
    return
# ... length limit on arguments_str, json.loads of both, depth limit on arguments ...
try:
    check_arguments_schema(schema, schema_str)
    validate_at_bounded_cost(schema, arguments, schema_str)
except RecursionError as exc:
    ...
except UnsupportedSchemaError as exc:
    ...
except jsonschema.SchemaError as exc:
    ...
except jsonschema.ValidationError as exc:
    ...
except Unresolvable as exc:
    ...
```

Every one of those becomes an `InvalidArgumentsException`, so a schema problem is a `400` and never a `500`.
`RecursionError` is in the list because a reference back to the root of the document (`{"$ref": "#"}`, 13 characters)
recurses without end, and no depth limit can see that coming.

Messages are truncated at `MAX_MESSAGE_LENGTH` (500 characters). `jsonschema` builds its messages with
`repr(instance)`, so without that a rejected payload came back to the caller in full.

The metaschema check is remembered by document text (`_check_schema_once`), since `check_schema` walks the whole
document, is pure, and a stored schema does not change between runs.

### On `/run`

`RunFunctionUseCase.execute` calls `validate_arguments(function, data.arguments)` **before** creating the `JobConfig`
and `Job` rows, and after the function has been resolved, permission-checked, and the active-job limit applied. A
rejected payload therefore leaves no orphaned rows behind and consumes no compute.

Order inside the use case:

1. Resolve the function → `FunctionNotFoundException` (404)
2. Function disabled → `FunctionDisabledException` (423)
3. Active job limit → `ActiveJobLimitExceeded` (429)
4. **Validate arguments** → `InvalidArgumentsException` (400)
5. Create `JobConfig` and `Job`

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
| Schema out of budget, refused keyword, unsupported regex, nested `$schema` | 400 | `{"message": "the function arguments schema cannot be used: ...", "path": []}` |
| Schema is not a valid JSON Schema, or not an object or boolean | 400 | `{"message": "the function arguments schema is not usable: ...", "path": []}` |
| Schema recurses without end | 400 | `{"message": "the function arguments schema recurses without end", "path": []}` |
| Schema references something unresolvable | 400 | `{"message": "... cannot be resolved: ...", "path": []}` |
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
  vendor uploads is what they read back. It also gives the metaschema check a stable cache key.
- **A dedicated exception instead of DRF's `ValidationError`,** so the 400 response can keep the `path` to the offending
  field instead of collapsing to one flat message.
- **A schema is refused at upload, not at run time.** The cost of evaluating a schema is a property of the schema, so
  the check belongs where the author can still act on the error. Validation applies the same rules again, because a
  schema stored before a rule existed must not become a way around it.
- **Expensive keywords are refused rather than budgeted.** A step counter only sees what goes through `descend`, so for
  keywords whose cost lives in private helpers the only safe options are replacing the keyword or refusing it.
