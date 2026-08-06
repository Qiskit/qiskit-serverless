# Argument validation

This document describes how a Qiskit Function declares the arguments it accepts, and how the gateway validates
submitted arguments against that declaration before any compute is used.

Without it, a function that receives bad input fails mid-execution: the user waits through queue time and container
startup only to get a runtime error. Vendors can now attach a [JSON Schema](https://json-schema.org/) to their function,
and the gateway rejects mismatching arguments at the API level, immediately and with a clear message.

The feature is opt-in and backwards compatible: a function without a schema is never validated.

## Where the schema lives

`Program.arguments_schema` (`gateway/core/models.py`), added by migration `0056_program_arguments_schema`:

```python
arguments_schema = models.TextField(null=True, blank=True, default="{}")
```

It stores the schema as **text**, not as a JSON column. The field is nullable, so the migration is rollback
compatible: old code inserting a `Program` row leaves the column `NULL`, and the read path treats `NULL` the same as
"no schema".

Both `NULL`/empty and `"{}"` mean *no validation*. There is no separate "validation enabled" flag.

## Declaring a schema

The schema is set through the existing upload endpoint, `POST /api/v1/programs/upload/`, as a regular form field
alongside `title`, `dependencies`, `env_vars` and the rest. It is metadata, not a file upload (the only file in that
request is the `artifact` tarball).

`ProgramSerializer` (`gateway/api/v1/views/programs/upload.py`) accepts it as an optional `CharField` and checks only
that the value **parses as JSON**:

```python
def validate_arguments_schema(self, value):
    """Validates that arguments_schema is valid JSON."""
    try:
        json.loads(value)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValidationError("arguments_schema must be valid JSON.") from exc
    return value
```

Whether the JSON is a *meaningful JSON Schema* is not checked here (see [Known gaps](#known-gaps)).

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

## Reading a schema back

`arguments_schema` is included in the output of both read endpoints, so a schema is not write-only:

| Endpoint | Serializer |
|---|---|
| `GET /api/v1/programs/get_by_title/<title>/` | `api/v1/views/programs/get_by_title.py` |
| `GET /api/v1/programs/` | `api/v1/views/programs/list.py` |

This lets a user inspect the arguments a function expects even when they did not upload it themselves. The value comes
back as the stored **string**, so the client SDK decodes it into a dict (see [Client SDK](#client-sdk)).

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

The function short-circuits when there is nothing to validate, decodes the arguments, and delegates to `jsonschema`
(dependency `jsonschema>=4.0.0,<5` in `gateway/requirements.txt`):

```python
schema_str = program.arguments_schema
if not schema_str or schema_str == "{}":
    return
schema = json.loads(schema_str)
if not schema:
    return
try:
    arguments = json.loads(arguments_str or "{}")
except json.JSONDecodeError as exc:
    raise InvalidArgumentsException(f"arguments is not valid JSON: {exc.msg}") from exc
try:
    jsonschema.validate(instance=arguments, schema=schema)
except jsonschema.ValidationError as exc:
    raise InvalidArgumentsException(exc.message, path=list(exc.path)) from exc
```

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

A provider function can be addressed either way, matching `/upload` and `/get_by_title`: as `title="acme/my-function"`
or as `title="my-function"` plus `provider="acme"`. `_split_provider_and_title` in the view applies the convention and
rejects the same two malformed cases `/upload` rejects: a provider given in both places, and more than one slash.

Note that `/run` does **not** split its `title`, so there a provider function must be addressed with `provider` as its
own field. The client SDK always separates the two in `QiskitFunction.__post_init__`, so SDK callers never notice the
difference; direct API callers do.

The view (`api/v1/views/programs/validate_arguments.py`) only parses and sanitizes input, then hands off to
`ValidateArgumentsUseCase`. Function resolution and permissions match `/run` exactly: `PLATFORM_PERMISSION_RUN` /
`RUN_PROGRAM_PERMISSION` for provider functions, `JobAccessPolicies.can_create` for a user's own functions. A function
the caller cannot reach is reported as not found, never as a permission error, so the endpoint does not leak the
existence of other vendors' functions.

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

| Situation | Exception | Status | Body |
|---|---|---|---|
| Arguments violate the schema | `InvalidArgumentsException` | 400 | `{"message": "...", "path": [...]}` |
| `arguments` is not valid JSON | `InvalidArgumentsException` | 400 | `{"message": "arguments is not valid JSON: ...", "path": []}` |
| Function missing or not accessible | `FunctionNotFoundException` | 404 | `{"message": "..."}` |
| `arguments_schema` is not valid JSON at upload | DRF `ValidationError` | 400 | `{"message": "arguments_schema must be valid JSON."}` |

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

## Known gaps

- **An invalid JSON Schema returns 500, not 400.** Upload only checks that `arguments_schema` parses as JSON, and the
  validation path catches `jsonschema.ValidationError` but not `jsonschema.SchemaError` (the two are unrelated classes,
  `SchemaError` is not a subclass of `ValidationError`). A schema with, say, a typo'd type (`{"type": "integar"}`) is
  accepted at upload, then makes `jsonschema.validate` raise `SchemaError`, which reaches the generic
  `except Exception` in the exception handler and is reported as `500 Internal server error`. Every run of that
  function fails that way until the schema is fixed. Two possible fixes: validate the schema itself at upload with
  `jsonschema.Draft7Validator.check_schema` (rejecting it up front, best for the vendor), and/or catch `SchemaError` in
  the validation path and surface it as a 400 or a dedicated 422.
