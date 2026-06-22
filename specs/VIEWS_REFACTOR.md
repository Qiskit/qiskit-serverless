# Views Refactor: Standalone Function Endpoints

## Goal

Replace DRF ViewSets with standalone function-based endpoints. Each HTTP method on each URL path becomes its own Python module, backed by a use case class that holds the business logic.

---

## Core Rules

1. **One function per path+method.** A `GET /programs/` and a `POST /programs/upload/` are two separate Python files — not two methods on the same ViewSet.

2. **One use case per endpoint** (when there is business logic). The view function has no logic of its own: it parses the request, calls the use case, and serializes the result.

3. **Serializers are for parsing and serializing only.** Never call `serializer.save()` in the new pattern. To persist data, call a repository method, a Django ORM method, or a use case that does so. Serializers exist to parse incoming JSON into validated Python objects and to convert domain objects back to JSON.

4. **Domain exceptions flow up.** The view never catches exceptions. It lets them propagate to `@endpoint_handle_exceptions`, which maps each exception type to an HTTP status code.

---

## Directory Layout

```
gateway/
  api/
    use_cases/
      <resource>/
        __init__.py
        list.py              # ListXxxUseCase
        get_by_title.py      # GetXxxByTitleUseCase
        create.py            # CreateXxxUseCase
    v1/
      views/
        <resource>/
          __init__.py        # empty or ViewSet remnant during migration
          list.py            # list_xxx view function
          get_by_title.py    # get_by_title view function
          create.py          # create_xxx view function
  tests/
    api/
      use_cases/
        <resource>/
          __init__.py
          test_list.py
          test_get_by_title.py
          test_create.py
```

The `views/` directory is walked recursively at boot by `import_dir` in `api/v1/urls.py`. Every `.py` file that contains an `@endpoint(...)` decorator is automatically registered — no manual `urlpatterns` editing needed.

---

## View Module Template

```python
"""API endpoint for <description>."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.<resource>.<action> import <XxxUseCase>
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.<resource>.<action>")


@swagger_auto_schema(
    method="get",
    operation_description="<Description>",
    responses={status.HTTP_200_OK: v1_serializers.XxxSerializer(many=True)},
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
    return Response(v1_serializers.XxxSerializer(result, many=True).data)
```

### Decorator order

The decorators must always appear in this exact top-to-bottom order:

```python
@swagger_auto_schema(...)            # 1 — Swagger metadata
@endpoint(..., method="GET", ...)    # 2 — registers the URL, wraps with api_view internally
@permission_classes([...])           # 3 — authentication/authorization
@endpoint_handle_exceptions          # 4 — catches domain exceptions
def my_view(request): ...
```

`@endpoint` accepts a required `method` argument and applies `api_view([method])` internally. Do **not** add a separate `@api_view` decorator — it is already handled.

Changing this order changes which decorator wraps which, and breaks either routing or exception handling.

---

## Use Case Template

### Simple case: returns a domain model

When the use case has a single success outcome, return the domain model directly.

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
        """Return the resource if found and accessible, else raise <Resource>NotFoundException."""
        instance = <Resource>.objects.get_by_title(user, title, provider, accessible_functions)
        if instance is None:
            raise <Resource>NotFoundException(<resource>=title, provider=provider)
        return instance
```

### Complex case: returns a response dataclass

When the use case can produce several structurally different outcomes (e.g. a redirect vs. inline data vs. empty), define a dataclass in a sibling `<action>_response.py` file and return it.

```python
# api/use_cases/<resource>/get_logs_response.py
from dataclasses import dataclass, field

@dataclass
class GetLogsResponse:
    raw_log: str | None = field(default=None)
    redirect_url: str | None = field(default=None)
```

```python
# api/use_cases/<resource>/get_logs.py
from api.use_cases.<resource>.get_logs_response import GetLogsResponse

class GetLogsUseCase:
    def execute(self, ...) -> GetLogsResponse:
        if needs_redirect:
            return GetLogsResponse(redirect_url=url)
        return GetLogsResponse(raw_log=log_text)
```

The view then inspects the dataclass fields and returns the appropriate HTTP response:

```python
result = GetLogsUseCase().execute(...)
if result.redirect_url:
    return HttpResponseRedirect(result.redirect_url)
if result.raw_log is None:
    return Response(status=status.HTTP_204_NO_CONTENT)
return Response({"logs": result.raw_log})
```

### Use case rules

- **Single public method:** `execute(self, user, accessible_functions, ...)`.
- **No HTTP imports.** No `Request`, no `Response`, no `status`. Pure Python.
- **Raise, don't return None for errors.** When a resource is not found or access is denied, raise the appropriate domain exception. The view stays ignorant of failure modes.
- **Return a domain model or a response dataclass.** For simple outcomes return the model directly. For multiple structural outcomes define a dataclass. Either way, serialization to JSON is the view's responsibility.
- **Exceptions must propagate unchanged.** Do not catch domain exceptions inside the use case and convert them to return values. They must reach `@endpoint_handle_exceptions` to be rendered as HTTP responses. The rendered format (status code, `{"message": "..."}` body) is the contract — do not replicate it manually in the view.

---

## Domain Exceptions

`@endpoint_handle_exceptions` maps exception types to HTTP status codes automatically:

| Exception | HTTP |
|-----------|------|
| `NotFoundError` and subclasses (`FunctionNotFoundException`, `JobNotFoundException`, ...) | 404 |
| `InvalidAccessException` | 403 |
| `ValidationError` (DRF) | 400 |
| `ActiveJobLimitExceeded` | 429 |
| `RuntimeFunctionsException` | 401 |
| Any other `Exception` | 500 |

To signal a 404 from a use case, raise the relevant subclass:

```python
raise FunctionNotFoundException(function="my-fn", provider="my-provider")
```

Do **not** catch exceptions in the view and build `Response({"message": ...}, 404)` manually — that pattern is what we are replacing.

---

## Logging Convention

Every view has exactly two log calls:

```python
# Before: log all inputs, always include accessible_functions
logger.info(
    "[<resource>-<action>] user_id=%s <field1>=%s accessible_functions=%s",
    user.id, value1, accessible_functions,
)

# After: log success (no accessible_functions needed here)
logger.info("[<resource>-<action>] user_id=%s | <Resource> <action> ok", user.id)
```

The `| ` separator before the success message is the project convention for the "done" line.

---

## Input Normalization

Query parameters and path parameters that need parsing or sanitization belong in a module-level helper function in the view module, **not** in the use case.

```python
def _parse_title_and_provider(title: str, provider: str | None) -> tuple[str, str | None]:
    """Split 'provider/title' convention or sanitize inputs."""
    if provider:
        return sanitize_name(title), sanitize_name(provider)
    parts = title.split("/")
    if len(parts) == 1:
        return sanitize_name(title), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])
```

The rule: anything that is about HTTP request format (splitting a path convention, decoding a query param, sanitizing a string) stays in the view layer. The use case receives clean, validated values.

---

## Unit Tests for Use Cases

Tests live next to the use case under `tests/api/use_cases/<resource>/`. They test the use case directly — no HTTP client, no `APIClient`, no URL reversals.

```python
"""Unit tests for Get<Resource>ByTitleUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.<resource>_not_found_exception import <Resource>NotFoundException
from api.use_cases.<resource>.get_by_title import Get<Resource>ByTitleUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import <Resource>, Provider, PLATFORM_PERMISSION_READ
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


class TestGet<Resource>ByTitleUseCase:
    def test_finds_own_resource(self, user):
        <Resource>.objects.create(title="my-item", author=user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = Get<Resource>ByTitleUseCase().execute(user, accessible, "my-item", None)

        assert result.title == "my-item"

    def test_raises_not_found_when_missing(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(<Resource>NotFoundException):
            Get<Resource>ByTitleUseCase().execute(user, accessible, "nonexistent", None)
```

Write the failing tests first, then implement the use case (TDD red-green cycle).

---

## What NOT to Do

**No serializer.save() in new views.**
Old pattern (ViewSet):
```python
serializer.save(author=request.user, title=title)
return Response(serializer.data)
```
New pattern:
```python
item = CreateItemUseCase().execute(user, accessible_functions, validated_data)
return Response(v1_serializers.ItemSerializer(item).data)
```

**No manual exception handling in new views.**
Old pattern:
```python
item = Item.objects.filter(title=title).first()
if item is None:
    return Response({"message": "Not found."}, status=404)
```
New pattern: raise in the use case, let `@endpoint_handle_exceptions` respond.

**No business logic in views.**
The view reads request fields, passes them to the use case, and returns the serialized result. Branching on domain state (checking permissions, deciding which ORM method to call) lives in the use case.

---

## Migration Checklist

When migrating an existing ViewSet action to this pattern:

- [ ] Create `api/use_cases/<resource>/<action>.py` with `execute(self, user, accessible_functions, ...)`.
- [ ] Write unit tests in `tests/api/use_cases/<resource>/test_<action>.py` (TDD — tests first).
- [ ] Create `api/v1/views/<resource>/<action>.py` with the view function and all four decorators.
- [ ] Remove the method from the base ViewSet (`api/views/<resource>.py`).
- [ ] Remove the override from the v1 ViewSet (`api/v1/views/<resource>/__init__.py`).
- [ ] Run `python manage.py check` — no issues.
- [ ] Run `python -m pytest tests/api/test_v1_<resource>.py tests/api/use_cases/<resource>/` — all passing.
