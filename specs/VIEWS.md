# Endpoint Development Guide

Every HTTP endpoint in the v1 API is a standalone function backed by a use case. There are no ViewSets or routers — all routes are registered via `@endpoint`.

---

## Directory Layout

```
gateway/
  api/
    use_cases/
      <resource>/
        <action>.py          # XxxUseCase
    v1/
      views/
        <resource>/
          __init__.py        # empty — module docstring only
          <action>.py        # view function
  tests/
    api/
      use_cases/
        <resource>/
          test_<action>.py   # use case unit tests
```

The `views/` directory is walked recursively at boot by `import_dir` in `api/v1/urls.py`. Every `.py` file containing an `@endpoint(...)` decorator is automatically registered — no manual `urlpatterns` editing.

---

## View Module

```python
"""API endpoint for <description>."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, serializers, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.<resource>.<action> import <XxxUseCase>
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import <Resource>

logger = logging.getLogger("api.api.v1.views.<resource>.<action>")


class OutputSerializer(serializers.ModelSerializer):
    """Response body for the /<resource>/<action> endpoint."""

    class Meta:
        model = <Resource>
        fields = [...]
        ref_name = "<Resource><Action>Output"


@swagger_auto_schema(
    method="get",
    operation_description="<Description>",
    responses={status.HTTP_200_OK: OutputSerializer(many=True)},
)
@endpoint("<resource>", method="GET", name="<resource>-<action>")
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def <action>_<resource>(request: Request) -> Response:
    """<One-line docstring>."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[<resource>-<action>] user_id=%s accessible_functions=%s",
        user.id,
        accessible_functions,
    )

    result = <XxxUseCase>().execute(user, accessible_functions, ...)
    logger.info("[<resource>-<action>] user_id=%s | <Resource> <action> ok", user.id)
    return Response(OutputSerializer(result, many=True).data)
```

---

## Serializers

### Rules

1. **Each view owns its serializers.** There is no central `api/v1/serializers.py`. Every serializer is defined in the view file that uses it — no cross-file imports of serializers.

2. **Import `serializers` without alias** — `from rest_framework import serializers`. There is no `api.v1.serializers` module to conflict with, so no alias is needed.

3. **Naming convention:**
   - `InputSerializer` — validates and sanitizes the request body or query params.
   - `OutputSerializer` — serializes the response object when there is a single output shape.
   - When output branches across multiple shapes (e.g. with/without `result`), use descriptive names (`JobSerializer`, `JobSerializerWithoutResult`) and a `serialize_output` function that picks the right one.

4. **Use `ref_name` in `Meta`** for every serializer so Swagger can disambiguate across views:
   ```python
   class Meta:
       model = Job
       fields = [...]
       ref_name = "JobsRetrieveOutput"
   ```

5. **`serialize_output` function** — when the response can't be expressed as a single `return Response(OutputSerializer(obj).data)`, define a standalone function:
   ```python
   def serialize_output(job: Job, with_result: bool):
       if with_result:
           return JobSerializer(job).data
       return JobSerializerWithoutResult(job).data
   ```
   The view then calls `return Response(serialize_output(job, with_result))`.

6. **Nested serializers stay in the same file.** A nested `ProgramSerializer` used only inside `OutputSerializer` is defined above it in the same file.

### Patterns

**Simple read (single output shape):**
```python
class OutputSerializer(serializers.ModelSerializer):
    provider = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Program
        fields = ["id", "title", "provider", ...]
        ref_name = "ProgramsListOutput"

# In the view function:
return Response(OutputSerializer(result, many=True).data)
```

**Write with input validation:**
```python
class InputSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    title = serializers.CharField(max_length=255)
    provider = serializers.CharField(required=False, allow_null=True)

    class Meta:
        ref_name = "ProgramsRunInput"

    def validate_title(self, value):
        """Sanitize title."""
        return sanitize_name(value)

# In the view function:
serializer = InputSerializer(data=request.data)
serializer.is_valid(raise_exception=True)
```

**Multiple output shapes:**
```python
class JobSerializer(serializers.ModelSerializer):
    program = ProgramSerializer(many=False)

    class Meta:
        model = Job
        fields = ["id", "result", "status", "program", ...]
        ref_name = "JobsRetrieveOutput"


class JobSerializerWithoutResult(serializers.ModelSerializer):
    program = ProgramSummary(read_only=True)

    class Meta:
        model = Job
        fields = ["id", "status", "program", ...]


def serialize_output(job: Job, with_result: bool):
    """Pick the right serializer based on the with_result flag."""
    if with_result:
        return JobSerializer(job).data
    return JobSerializerWithoutResult(job).data

# In the view function:
return Response(serialize_output(job, with_result))
```

---

### Decorator order

Always in this exact order — changing it breaks routing or exception handling:

```python
@swagger_auto_schema(...)       # 1 — Swagger metadata
@endpoint(..., method="GET")    # 2 — registers URL, wraps with api_view internally
@permission_classes([...])      # 3 — authentication/authorization
@endpoint_handle_exceptions     # 4 — maps domain exceptions to HTTP responses
def my_view(request): ...
```

`@endpoint` applies `api_view([method])` internally. Do **not** add a separate `@api_view`.

---

## Use Case

### Simple case

```python
"""Use case: <description>."""

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.<resource>_not_found_exception import <Resource>NotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import <Resource>


class Get<Resource>ByTitleUseCase:
    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        title: str,
        provider: str | None,
    ) -> <Resource>:
        instance = <Resource>.objects.get_by_title(user, title, provider, accessible_functions)
        if instance is None:
            raise <Resource>NotFoundException(resource=title, provider=provider)
        return instance
```

### Complex case (multiple outcome shapes)

Define a dataclass in a sibling `<action>_response.py`:

```python
# api/use_cases/<resource>/get_logs_response.py
from dataclasses import dataclass, field

@dataclass
class GetLogsResponse:
    raw_log: str | None = field(default=None)
    redirect_url: str | None = field(default=None)
```

The view inspects the dataclass and builds the appropriate HTTP response.

### Use case rules

- **Single public method:** `execute(self, user, accessible_functions, ...)`.
- **No HTTP imports.** No `Request`, `Response`, or `status`. Pure Python.
- **Raise on errors, never return `None`.** Use the appropriate domain exception.
- **Serializers are for parsing and formatting only.** Persistence goes in the use case via ORM calls, never via `serializer.save()`.

---

## Input Dataclasses

For write operations (create, run) where the view must pass multiple validated fields to the use case, define an input dataclass in `api/use_cases/<resource>/<action>_input.py`. The dataclass owns the conversion from serializer validated data.

```python
# api/use_cases/programs/upload_input.py
from dataclasses import dataclass

from api.utils import sanitize_name


@dataclass
class UploadFunctionInput:
    title: str
    provider: str | None
    # ... other fields

    @classmethod
    def from_validated_data(cls, data: dict) -> "UploadFunctionInput":
        title, provider = _parse_provider_and_title(data["title"])
        return cls(title=title, provider=provider, ...)


def _parse_provider_and_title(raw: str) -> tuple[str, str | None]:
    parts = raw.split("/")
    if len(parts) == 1:
        return sanitize_name(raw), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])
```

The view calls `from_validated_data` after `serializer.is_valid()` and passes the dataclass to the use case:

```python
input_data = UploadFunctionInput.from_validated_data(serializer.validated_data)
result = UploadFunctionUseCase().execute(user, accessible_functions, input_data)
```

The use case receives a fully-typed, clean dataclass — no raw dicts, no HTTP concerns.

**When to use:** any endpoint where more than two or three fields flow from the view to the use case. Simple lookups (title + provider) can use plain keyword arguments.

---

## Exception Handling

`@endpoint_handle_exceptions` maps exception types to HTTP status codes automatically:

| Exception | HTTP |
|-----------|------|
| `FunctionNotFoundException`, `JobNotFoundException`, other `NotFoundError` subclasses | 404 |
| `FunctionDisabledException` | 423 |
| `InvalidAccessException` | 403 |
| `ValidationError` (DRF) | 400 |
| `ActiveJobLimitExceeded` | 429 |
| `RuntimeFunctionsException` | 401 |
| Any other `Exception` | 500 |

The view never catches exceptions. It lets them reach `@endpoint_handle_exceptions`.

---

## Logging Convention

Every view has exactly two log calls:

```python
# Before the use case: log all inputs
logger.info(
    "[<resource>-<action>] user_id=%s <field>=%s accessible_functions=%s",
    user.id, value, accessible_functions,
)

# After: log success with " | " separator
logger.info("[<resource>-<action>] user_id=%s | <Resource> <action> ok", user.id)
```

---

## Input Normalization

Parsing or sanitizing request parameters belongs in a module-level helper in the view, not in the use case. The use case receives clean values.

```python
def _parse_title_and_provider(title: str, provider: str | None) -> tuple[str, str | None]:
    if provider:
        return sanitize_name(title), sanitize_name(provider)
    parts = title.split("/")
    if len(parts) == 1:
        return sanitize_name(title), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])
```

### View vs use case: where does validation belong?

| Validation type | Where |
|---|---|
| Format/parsing (sanitize, regex, type coercion) | View (serializer validators or `_parse_*` helper) |
| Sub-object shape (e.g. `JobConfigSerializer`) | View (serializer) |
| Business rules (quota limits, existence checks, permissions) | Use case |

Concretely: `sanitize_name` on `title` and `provider` must be applied symmetrically in **every** serializer that accepts those fields (`UploadProgramSerializer`, `RunProgramSerializer`, etc.) — an asymmetry causes functions to become unreachable via one endpoint even though they exist. Quota checks (`active_jobs_limit_reached`) go in the use case, after the function is resolved, so that non-existent or unauthorized functions return 404/403 rather than leaking quota state.

---

## Unit Tests

Tests live in `tests/api/use_cases/<resource>/` and test the use case directly — no HTTP client, no URL reversals.

```python
"""Unit tests for <XxxUseCase>."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.<resource>_not_found_exception import <Resource>NotFoundException
from api.use_cases.<resource>.<action> import <XxxUseCase>
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import <Resource>

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class Test<XxxUseCase>:
    def test_<happy_path>(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=True, functions=[])

        result = <XxxUseCase>().execute(user, accessible, ...)

        assert result.<field> == <expected>

    def test_raises_not_found_when_missing(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(<Resource>NotFoundException):
            <XxxUseCase>().execute(user, accessible, "nonexistent", None)
```
