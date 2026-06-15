# Programs Endpoints Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the `programs` DRF ViewSet to standalone function-based v1 endpoints, split across two PRs.

**Architecture:** PR 1 extracts `list` and `get_by_title` into standalone views backed by use cases that raise domain exceptions, following the exact pattern of `api/v1/views/jobs/get_logs.py`. PR 2 moves `upload` and `run` to the same structural pattern without extracting use cases, then deletes the ViewSet entirely.

**Tech Stack:** Django REST Framework, drf-yasg, pytest-django, existing `@endpoint` / `@endpoint_handle_exceptions` decorators.

---

## Reference: existing pattern

Study these files before starting. Every new file should look like them:

- `gateway/api/v1/views/jobs/get_logs.py` — view structure to copy
- `gateway/api/use_cases/jobs/list.py` — use case structure to copy
- `gateway/tests/api/use_cases/jobs/test_retrieve.py` — test structure to copy

---

## PR 1 — Read endpoints with use cases

### File map

| Action | File |
|--------|------|
| Create | `gateway/api/use_cases/programs/__init__.py` |
| Create | `gateway/api/use_cases/programs/list.py` |
| Create | `gateway/api/use_cases/programs/get_by_title.py` |
| Move   | `gateway/api/v1/views/programs.py` → `gateway/api/v1/views/programs/__init__.py` |
| Create | `gateway/api/v1/views/programs/list.py` |
| Create | `gateway/api/v1/views/programs/get_by_title.py` |
| Create | `gateway/tests/api/use_cases/programs/__init__.py` |
| Create | `gateway/tests/api/use_cases/programs/test_list.py` |
| Create | `gateway/tests/api/use_cases/programs/test_get_by_title.py` |
| Modify | `gateway/api/views/programs.py` — remove `list` and `get_by_title` methods |
| Modify | `gateway/api/v1/views/programs/__init__.py` — remove `list` and `get_by_title` overrides |

---

### Task 1: Scaffold directories

> **Important:** Python cannot have both `programs.py` and a `programs/` package in the same directory — the package takes precedence and breaks `from .programs import ProgramViewSet`. The solution is to move the ViewSet into the package's `__init__.py` before creating any other files inside `programs/`.

**Files:**
- Create: `gateway/api/use_cases/programs/__init__.py`
- Move: `gateway/api/v1/views/programs.py` → `gateway/api/v1/views/programs/__init__.py`
- Create: `gateway/tests/api/use_cases/programs/__init__.py`

- [ ] **Step 1: Create use_cases and tests scaffold**

```bash
touch gateway/api/use_cases/programs/__init__.py
touch gateway/tests/api/use_cases/programs/__init__.py
```

- [ ] **Step 2: Convert `api/v1/views/programs.py` into a package**

```bash
mkdir -p gateway/api/v1/views/programs
mv gateway/api/v1/views/programs.py gateway/api/v1/views/programs/__init__.py
```

After this step `gateway/api/v1/views/__init__.py` still imports `from .programs import ProgramViewSet` — this now resolves to the package's `__init__.py`, so no code change is needed there.

- [ ] **Step 3: Verify Django still starts**

```bash
cd gateway && python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Run all tests to confirm nothing broke**

```bash
cd gateway && python -m pytest tests/api/test_v1_program.py -q
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add gateway/api/use_cases/programs/__init__.py \
        gateway/tests/api/use_cases/programs/__init__.py
git mv gateway/api/v1/views/programs.py gateway/api/v1/views/programs/__init__.py 2>/dev/null || true
git add gateway/api/v1/views/programs/__init__.py
git commit -m "convert v1 programs view to package to allow endpoint submodules"
```

---

### Task 2: ListFunctionsUseCase (TDD)

**Files:**
- Create: `gateway/api/use_cases/programs/list.py`
- Create: `gateway/tests/api/use_cases/programs/test_list.py`

- [ ] **Step 1: Write the failing tests**

Create `gateway/tests/api/use_cases/programs/test_list.py`:

```python
"""Unit tests for ListFunctionsUseCase."""

import pytest
from django.contrib.auth.models import User

from api.use_cases.programs.list import ListFunctionsUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider, PLATFORM_PERMISSION_READ
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture
def provider():
    return Provider.objects.create(name="my-provider")


class TestListFunctionsUseCase:
    def test_serverless_filter_returns_only_own_functions(self, user, other_user):
        Program.objects.create(title="my-fn", author=user)
        Program.objects.create(title="other-fn", author=other_user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, "serverless")

        assert len(result) == 1
        assert result[0].title == "my-fn"

    def test_catalog_filter_returns_provider_functions_with_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = ListFunctionsUseCase().execute(user, accessible, "catalog")

        assert len(result) == 1
        assert result[0].title == "provider-fn"

    def test_catalog_filter_excludes_functions_without_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, "catalog")

        assert result == []

    def test_no_filter_returns_own_and_accessible_provider_functions(self, user, provider):
        Program.objects.create(title="my-fn", author=user)
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = ListFunctionsUseCase().execute(user, accessible, None)

        titles = {f.title for f in result}
        assert "my-fn" in titles
        assert "provider-fn" in titles

    def test_empty_list_when_no_functions_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = ListFunctionsUseCase().execute(user, accessible, None)

        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/api/use_cases/programs/test_list.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` for `api.use_cases.programs.list`.

- [ ] **Step 3: Implement ListFunctionsUseCase**

Create `gateway/api/use_cases/programs/list.py`:

```python
"""Use case: list Qiskit Functions for a user."""

from django.contrib.auth.models import AbstractUser

from core.domain.authorization.function_access_result import FunctionAccessResult
from core.enums.type_filter import TypeFilter
from core.models import (
    PLATFORM_PERMISSION_READ,
    RUN_PROGRAM_PERMISSION,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)


class ListFunctionsUseCase:
    """Use case for listing Qiskit Functions accessible to a user."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        type_filter: str | None,
    ) -> list[Function]:
        """Return functions the user can see, filtered by type_filter."""
        if type_filter == TypeFilter.SERVERLESS:
            return list(Function.objects.user_functions(user))

        if type_filter == TypeFilter.CATALOG:
            return list(
                Function.objects.provider_functions().with_permission(
                    user,
                    accessible_functions=accessible_functions,
                    legacy_permission_name=RUN_PROGRAM_PERMISSION,
                    permission=PLATFORM_PERMISSION_READ,
                )
            )

        return list(
            Function.objects.with_permission(
                user,
                accessible_functions=accessible_functions,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
                permission=PLATFORM_PERMISSION_READ,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/api/use_cases/programs/test_list.py -v
```

Expected: 5 tests passing.

- [ ] **Step 5: Commit**

```bash
git add gateway/api/use_cases/programs/list.py \
        gateway/tests/api/use_cases/programs/test_list.py
git commit -m "add ListFunctionsUseCase with tests"
```

---

### Task 3: GetFunctionByTitleUseCase (TDD)

**Files:**
- Create: `gateway/api/use_cases/programs/get_by_title.py`
- Create: `gateway/tests/api/use_cases/programs/test_get_by_title.py`

- [ ] **Step 1: Write the failing tests**

Create `gateway/tests/api/use_cases/programs/test_get_by_title.py`:

```python
"""Unit tests for GetFunctionByTitleUseCase."""

import pytest
from django.contrib.auth.models import User

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.use_cases.programs.get_by_title import GetFunctionByTitleUseCase
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Program, Provider, PLATFORM_PERMISSION_READ
from tests.utils import create_function_access_result

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(username="author")


@pytest.fixture
def other_user():
    return User.objects.create_user(username="other")


@pytest.fixture
def provider():
    return Provider.objects.create(name="my-provider")


class TestGetFunctionByTitleUseCase:
    def test_finds_own_serverless_function(self, user):
        Program.objects.create(title="my-fn", author=user)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        result = GetFunctionByTitleUseCase().execute(user, accessible, "my-fn", None)

        assert result.title == "my-fn"

    def test_finds_provider_function_with_permission(self, user, provider):
        Program.objects.create(title="provider-fn", author=user, provider=provider)
        accessible = create_function_access_result("my-provider", "provider-fn", {PLATFORM_PERMISSION_READ})

        result = GetFunctionByTitleUseCase().execute(user, accessible, "provider-fn", "my-provider")

        assert result.title == "provider-fn"

    def test_raises_not_found_when_function_does_not_exist(self, user):
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "nonexistent", None)

    def test_raises_not_found_when_no_access_to_provider_function(self, user, other_user, provider):
        Program.objects.create(title="provider-fn", author=other_user, provider=provider)
        accessible = FunctionAccessResult(use_legacy_authorization=False, functions=[])

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "provider-fn", "my-provider")

    def test_raises_not_found_when_provider_function_not_found(self, user, provider):
        accessible = create_function_access_result("my-provider", "ghost-fn", {PLATFORM_PERMISSION_READ})

        with pytest.raises(FunctionNotFoundException):
            GetFunctionByTitleUseCase().execute(user, accessible, "ghost-fn", "my-provider")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd gateway && python -m pytest tests/api/use_cases/programs/test_get_by_title.py -v
```

Expected: `ImportError` for `api.use_cases.programs.get_by_title`.

- [ ] **Step 3: Implement GetFunctionByTitleUseCase**

Create `gateway/api/use_cases/programs/get_by_title.py`:

```python
"""Use case: retrieve a Qiskit Function by title."""

from django.contrib.auth.models import AbstractUser

from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_READ,
    VIEW_PROGRAM_PERMISSION,
    Program as Function,
)


class GetFunctionByTitleUseCase:
    """Use case for retrieving a single Qiskit Function by title and optional provider."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        title: str,
        provider: str | None,
    ) -> Function:
        """Return the function if found and accessible, else raise FunctionNotFoundException.

        Both "not found" and "no access" raise the same exception to avoid
        leaking information about function existence.
        """
        if provider:
            function = Function.objects.get_function_by_permission(
                user=user,
                function_title=title,
                provider_name=provider,
                accessible_functions=accessible_functions,
                permission=PLATFORM_PERMISSION_READ,
                legacy_permission_name=VIEW_PROGRAM_PERMISSION,
            )
        else:
            function = Function.objects.get_user_function(user, title)

        if function is None:
            raise FunctionNotFoundException(function=title, provider=provider)

        return function
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd gateway && python -m pytest tests/api/use_cases/programs/test_get_by_title.py -v
```

Expected: 5 tests passing.

- [ ] **Step 5: Commit**

```bash
git add gateway/api/use_cases/programs/get_by_title.py \
        gateway/tests/api/use_cases/programs/test_get_by_title.py
git commit -m "add GetFunctionByTitleUseCase with tests"
```

---

### Task 4: list_programs view

**Files:**
- Create: `gateway/api/v1/views/programs/list.py`

- [ ] **Step 1: Create the view**

Create `gateway/api/v1/views/programs/list.py`:

```python
"""API endpoint for listing Qiskit Functions."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.list import ListFunctionsUseCase
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.list")


@swagger_auto_schema(
    method="get",
    operation_description="List author Qiskit Functions",
    manual_parameters=[
        openapi.Parameter(
            "filter",
            openapi.IN_QUERY,
            description="Filters that you can apply for list: serverless, catalog or empty",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={status.HTTP_200_OK: v1_serializers.ProgramSerializer(many=True)},
)
@endpoint("programs", name="programs-list")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def list_programs(request: Request) -> Response:
    """List Qiskit Functions accessible to the authenticated user."""
    type_filter = request.query_params.get("filter")
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-list] user_id=%s filter=%s accessible_functions=%s",
        user.id,
        type_filter,
        accessible_functions,
    )

    functions = ListFunctionsUseCase().execute(user, accessible_functions, type_filter)
    logger.info("[programs-list] user_id=%s filter=%s | Functions listed ok", user.id, type_filter)
    return Response(v1_serializers.ProgramSerializer(functions, many=True).data)
```

- [ ] **Step 2: Remove `list` from the base ViewSet**

In `gateway/api/views/programs.py`, delete the entire `list` method (lines starting at `@_trace` through the final `return Response(serializer.data)` of that method). Also remove `TypeFilter` from imports if it's no longer used anywhere else in the file. The `accessible_functions` import line is also used by `upload`, `run`, and `get_by_title` so leave it.

- [ ] **Step 3: Remove `list` override from the v1 ViewSet**

In `gateway/api/v1/views/programs/__init__.py`, delete the `list` method (the one decorated with `@swagger_auto_schema` that calls `super().list(request)`).

- [ ] **Step 4: Verify the route is now served by the new view**

```bash
cd gateway && python manage.py show_urls 2>/dev/null | grep "programs" || python -c "
import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings'); django.setup()
from django.urls import reverse; print(reverse('programs-list'))
"
```

Expected: `/api/v1/programs/`

- [ ] **Step 5: Run all program-related tests**

```bash
cd gateway && python -m pytest tests/api/test_v1_program.py tests/api/use_cases/programs/ -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add gateway/api/v1/views/programs/list.py \
        gateway/api/views/programs.py \
        gateway/api/v1/views/programs.py
git commit -m "migrate programs list endpoint to standalone function view"
```

---

### Task 5: get_by_title view

**Files:**
- Create: `gateway/api/v1/views/programs/get_by_title.py`

- [ ] **Step 1: Create the view**

Create `gateway/api/v1/views/programs/get_by_title.py`:

```python
"""API endpoint for retrieving a Qiskit Function by title."""

import logging
from typing import cast

from django.contrib.auth.models import AbstractUser
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.use_cases.programs.get_by_title import GetFunctionByTitleUseCase
from api.utils import sanitize_name
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from api.v1.views.swagger_utils import standard_error_responses
from core.domain.authorization.function_access_result import FunctionAccessResult

logger = logging.getLogger("api.api.v1.views.programs.get_by_title")


def _parse_title_and_provider(title: str, provider: str | None) -> tuple[str, str | None]:
    """Split 'provider/title' convention or sanitize inputs."""
    if provider:
        return sanitize_name(title), sanitize_name(provider)
    parts = title.split("/")
    if len(parts) == 1:
        return sanitize_name(title), None
    return sanitize_name(parts[1]), sanitize_name(parts[0])


@swagger_auto_schema(
    method="get",
    operation_description="Retrieve a Qiskit Function using the title",
    manual_parameters=[
        openapi.Parameter(
            "title",
            openapi.IN_PATH,
            description="The title of the function",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="The provider in case the function is owned by a provider",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
    responses={
        status.HTTP_200_OK: v1_serializers.ProgramSerializer,
        **standard_error_responses(not_found_example="Qiskit Function [XXX] doesn't exist."),
    },
)
@endpoint("programs/get_by_title/<str:title>", name="programs-get-by-title")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def get_by_title(request: Request, title: str) -> Response:
    """Retrieve a single Qiskit Function by title."""
    user = cast(AbstractUser, request.user)
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    function_title, provider_name = _parse_title_and_provider(
        title, request.query_params.get("provider")
    )
    logger.info(
        "[programs-get-by-title] user_id=%s program=%s provider=%s accessible_functions=%s",
        user.id,
        function_title,
        provider_name,
        accessible_functions,
    )

    function = GetFunctionByTitleUseCase().execute(user, accessible_functions, function_title, provider_name)
    logger.info(
        "[programs-get-by-title] user_id=%s program=%s provider=%s | Function retrieved ok",
        user.id,
        function_title,
        provider_name,
    )
    return Response(v1_serializers.ProgramSerializer(function).data)
```

- [ ] **Step 2: Remove `get_by_title` from the base ViewSet**

In `gateway/api/views/programs.py`, delete the entire `get_by_title` method. Also remove any imports that are now unused (check `sanitize_name` — it's used by `run` too, so keep it).

- [ ] **Step 3: Remove `get_by_title` override from the v1 ViewSet**

In `gateway/api/v1/views/programs/__init__.py`, delete the `get_by_title` method (swagger-decorated, calls `super().get_by_title(...)`).

- [ ] **Step 4: Run all tests**

```bash
cd gateway && python -m pytest tests/api/test_v1_program.py tests/api/use_cases/programs/ -v
```

Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add gateway/api/v1/views/programs/get_by_title.py \
        gateway/api/views/programs.py \
        gateway/api/v1/views/programs.py
git commit -m "migrate programs get_by_title endpoint to standalone function view"
```

---

### Task 6: PR 1 final verification

- [ ] **Step 1: Run full test suite**

```bash
cd gateway && python -m pytest tests/ -x -q
```

Expected: all passing, no failures.

- [ ] **Step 2: Verify Django system check**

```bash
cd gateway && python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

---

## PR 2 — Write endpoints + ViewSet deletion

Start PR 2 on a new branch from the merge of PR 1.

### File map

| Action | File |
|--------|------|
| Create | `gateway/api/v1/views/programs/upload.py` |
| Create | `gateway/api/v1/views/programs/run.py` |
| Delete | `gateway/api/views/programs.py` |
| Clear  | `gateway/api/v1/views/programs/__init__.py` — replace ViewSet content with empty module |
| Modify | `gateway/api/v1/views/__init__.py` — remove `ProgramViewSet` export |
| Modify | `gateway/api/v1/urls.py` — remove router registration |

---

### Task 7: upload view

**Files:**
- Create: `gateway/api/v1/views/programs/upload.py`

- [ ] **Step 1: Create the view**

This is the `upload` method from `gateway/api/views/programs.py` adapted to a standalone function. Replace `self.get_serializer_upload_program(...)` with `v1_serializers.UploadProgramSerializer(...)` and `self.get_serializer(function)` with `v1_serializers.ProgramSerializer(function)`. Remove `@_trace`. Keep all business logic unchanged.

Create `gateway/api/v1/views/programs/upload.py`:

```python
"""API endpoint for uploading a Qiskit Function."""

import logging
from typing import cast

from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.access_policies.programs import ProgramAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import Provider
from core.models import Program as Function

logger = logging.getLogger("api.api.v1.views.programs.upload")


@swagger_auto_schema(
    method="post",
    operation_description="Upload a Qiskit Function",
    request_body=v1_serializers.UploadProgramSerializer,
    responses={status.HTTP_200_OK: v1_serializers.UploadProgramSerializer},
)
@endpoint("programs/upload", name="programs-upload")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def upload(request: Request) -> Response:
    """Upload or update a Qiskit Function."""
    serializer = v1_serializers.UploadProgramSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error(
            "[programs-upload] user_id=%s validation failed: %s",
            request.user.id,
            serializer.errors,
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    title = serializer.validated_data.get("title")
    request_provider = serializer.validated_data.get("provider", None)
    author = request.user
    provider_name, title = serializer.get_provider_name_and_title(request_provider, title)

    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-upload] user_id=%s program=%s provider=%s accessible_functions=%s",
        author.id,
        title,
        provider_name,
        accessible_functions,
    )

    program = None
    if provider_name:
        provider_obj = Provider.objects.filter(name=provider_name).first()
        if provider_obj is None or not ProviderAccessPolicy.can_upload_function(
            user=author,
            provider=provider_obj,
            function_title=title,
            accessible_functions=accessible_functions,
        ):
            return Response(
                {"message": f"Provider [{provider_name}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        program = serializer.retrieve_provider_function(title=title, provider_name=provider_name)
    else:
        if not ProgramAccessPolicies.can_create(user=author, accessible_functions=accessible_functions):
            return Response(
                {"message": f"Custom function [{title}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        program = serializer.retrieve_private_function(title=title, author=author)

    if program is not None:
        serializer = v1_serializers.UploadProgramSerializer(program, data=request.data)
        if not serializer.is_valid():
            logger.error(
                "[programs-upload] user_id=%s validation failed on update: %s",
                author.id,
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    runner = serializer.validated_data.get("runner", Function.RAY)
    serializer.save(author=author, title=title, provider=provider_name, runner=runner)

    logger.info(
        "[programs-upload] user_id=%s program=%s provider=%s runner=%s | Function uploaded ok",
        author.id,
        title,
        provider_name,
        runner,
    )
    return Response(serializer.data)
```

- [ ] **Step 2: Run upload-related integration tests**

```bash
cd gateway && python -m pytest tests/api/test_v1_program.py -k "upload" -v
```

Expected: all passing (the router still serves `/programs/upload/` while the new route also registers it — both resolve to the same path, RouteRegistry wins as it appears first in `urlpatterns`).

- [ ] **Step 3: Commit**

```bash
git add gateway/api/v1/views/programs/upload.py
git commit -m "migrate programs upload endpoint to standalone function view"
```

---

### Task 8: run view

**Files:**
- Create: `gateway/api/v1/views/programs/run.py`

- [ ] **Step 1: Create the view**

This is the `run` method from `gateway/api/views/programs.py` adapted to a standalone function. Replace `self.get_serializer_run_program(...)`, `self.get_serializer_job_config(...)`, and `self.get_serializer_run_job(...)` with the corresponding `v1_serializers` classes. Remove `@_trace`. Keep all business logic unchanged.

Create `gateway/api/v1/views/programs/run.py`:

```python
"""API endpoint for running a Qiskit Function."""

import logging
import re
from typing import cast

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from drf_yasg.utils import swagger_auto_schema
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from api.access_policies.jobs import JobAccessPolicies
from api.domain.authentication.channel import Channel
from api.domain.exceptions.active_job_limit_exceeded_exception import ActiveJobLimitExceeded
from api.utils import active_jobs_limit_reached, sanitize_name
from api.v1 import serializers as v1_serializers
from api.v1.endpoint_decorator import endpoint
from api.v1.exception_handler import endpoint_handle_exceptions
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    PLATFORM_PERMISSION_RUN,
    RUN_PROGRAM_PERMISSION,
    Program as Function,
)

logger = logging.getLogger("api.api.v1.views.programs.run")


@swagger_auto_schema(
    method="post",
    operation_description="Run an existing Qiskit Function",
    request_body=v1_serializers.RunProgramSerializer,
    responses={status.HTTP_200_OK: v1_serializers.RunJobSerializer},
)
@endpoint("programs/run", name="programs-run")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@endpoint_handle_exceptions
def run(  # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches,too-many-statements
    request: Request,
) -> Response:
    """Enqueue an existing Qiskit Function as a job."""
    serializer = v1_serializers.RunProgramSerializer(data=request.data)
    if not serializer.is_valid():
        logger.error(
            "[programs-run] user_id=%s RunProgramSerializer validation failed: %s",
            request.user.id,
            serializer.errors,
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    author = cast(AbstractUser, request.user)
    provider_name = sanitize_name(serializer.data.get("provider"))
    function_title = sanitize_name(serializer.data.get("title"))
    accessible_functions = cast(FunctionAccessResult, request.auth.accessible_functions)
    logger.info(
        "[programs-run] user_id=%s program=%s provider=%s accessible_functions=%s",
        author.id,
        function_title,
        provider_name,
        accessible_functions,
    )

    function = None
    if provider_name:
        function = Function.objects.get_function_by_permission(
            user=author,
            function_title=function_title,
            provider_name=provider_name,
            accessible_functions=accessible_functions,
            permission=PLATFORM_PERMISSION_RUN,
            legacy_permission_name=RUN_PROGRAM_PERMISSION,
        )
    else:
        if JobAccessPolicies.can_create(user=author, accessible_functions=accessible_functions):
            function = Function.objects.get_user_function(author, function_title)

    if function is None:
        logger.error("[programs-run] user_id=%s function not found: %s", author.id, function_title)
        return Response(
            {"message": f"Qiskit Pattern [{function_title}] was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if function.disabled:
        error_message = (
            function.disabled_message if function.disabled_message else Function.DEFAULT_DISABLED_MESSAGE
        )
        return Response({"message": error_message}, status=status.HTTP_423_LOCKED)

    jobconfig = None
    config_json = serializer.data.get("config")
    if config_json:
        job_config_serializer = v1_serializers.JobConfigSerializer(data=config_json)
        if not job_config_serializer.is_valid():
            logger.error(
                "[programs-run] user_id=%s JobConfigSerializer validation failed: %s",
                author.id,
                serializer.errors,
            )
            return Response(job_config_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        jobconfig = job_config_serializer.save()

    carrier = {}
    TraceContextTextMapPropagator().inject(carrier)
    arguments = serializer.data.get("arguments")
    channel = Channel.IBM_QUANTUM_PLATFORM
    token = ""
    instance = None
    account_id = None
    if request.auth:
        channel = request.auth.channel
        token = request.auth.token.decode()
        instance = request.auth.instance
        account_id = request.auth.account_id

    job_data = {"arguments": arguments, "program": function.id}
    job_serializer = v1_serializers.RunJobSerializer(data=job_data)
    if not job_serializer.is_valid():
        logger.error(
            "[programs-run] user_id=%s RunJobSerializer validation failed: %s",
            author.id,
            serializer.errors,
        )
        return Response(job_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    if active_jobs_limit_reached(author):
        logger.error(
            "[programs-run] user_id=%s active jobs limit reached (%s)",
            author.id,
            settings.LIMITS_ACTIVE_JOBS_PER_USER,
        )
        raise ActiveJobLimitExceeded()

    compute_profile = request.data.get("compute_profile")
    if compute_profile:
        if not re.match(r"^[a-z]+\d+[a-z]?-\d+x\d+(?:x\d+[a-z0-9]+)?$", compute_profile):
            error_msg = (
                f"Invalid compute profile format: '{compute_profile}'. "
                f"Expected format: [type]-[cpu]x[memory] or [type]-[cpu]x[memory]x[gpu_count][gpu_type] "
                f"(lowercase only, e.g., 'cx3d-4x16' or 'gx3d-24x120x1a100p')"
            )
            return Response({"compute_profile": [error_msg]}, status=status.HTTP_400_BAD_REQUEST)

    business_model = None
    if provider_name and not accessible_functions.use_legacy_authorization:
        business_model = accessible_functions.get_function(provider_name, function_title).business_model

    save_kwargs = {
        "author": author,
        "carrier": carrier,
        "channel": channel,
        "token": token,
        "config": jobconfig,
        "instance": instance,
        "account_id": account_id,
        "compute_profile": compute_profile,
        "business_model": business_model,
    }
    job = job_serializer.save(**save_kwargs)
    logger.info("[programs-run] user_id=%s job_id=%s program=%s | Job queued ok", author.id, job.id, function_title)
    return Response(job_serializer.data)
```

- [ ] **Step 2: Run run-related integration tests**

```bash
cd gateway && python -m pytest tests/api/test_v1_program.py -k "run" -v
```

Expected: all passing.

- [ ] **Step 3: Commit**

```bash
git add gateway/api/v1/views/programs/run.py
git commit -m "migrate programs run endpoint to standalone function view"
```

---

### Task 9: Delete ViewSet and clean up routing

**Files:**
- Delete: `gateway/api/views/programs.py`
- Delete: `gateway/api/v1/views/programs.py`
- Modify: `gateway/api/v1/views/__init__.py`
- Modify: `gateway/api/v1/urls.py`

- [ ] **Step 1: Delete the base ViewSet and clear the v1 package `__init__.py`**

```bash
git rm gateway/api/views/programs.py
```

Replace `gateway/api/v1/views/programs/__init__.py` with an empty module (the ViewSet code is no longer needed):

```python
"""Qiskit Function views package."""
```

- [ ] **Step 2: Update `gateway/api/v1/views/__init__.py`**

Remove the `ProgramViewSet` export. The file currently contains:

```python
from .programs import ProgramViewSet
```

Replace it with an empty file (just the module docstring):

```python
"""
Django Rest framework ViewSets for api application:

Specification for V1 version of the API.
"""
```

- [ ] **Step 3: Update `gateway/api/v1/urls.py`**

Remove the router registration. The current file has:

```python
from api.v1 import views as v1_views
# ...
router = SimpleRouter()
router.register(
    r"programs",
    v1_views.ProgramViewSet,
    basename=v1_views.ProgramViewSet.BASE_NAME,
)

urlpatterns = RouteRegistry.get() + router.urls
```

Replace with (keep `import_dir` and `RouteRegistry` logic, remove router entirely):

```python
"""
URL Patterns for V1 api application.
"""

import os
import importlib
import logging

from api.v1.route_registry import RouteRegistry

logger = logging.getLogger("api.api.v1.urls")


###
# Force imports of every view module
###
views_dir = os.path.join(os.path.dirname(__file__), "views")
BASE_MODULE = "api.v1.views"


def import_dir(directory: str, base_module: str):
    """Force imports of every view module"""
    for filename in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, filename)):
            import_dir(os.path.join(directory, filename), f"{base_module}.{filename}")
        elif filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            importlib.import_module(f"{base_module}.{module_name}")
            logger.debug("[BOOT] Import api.v1.views.%s", module_name)


import_dir(views_dir, BASE_MODULE)

urlpatterns = RouteRegistry.get()
```

- [ ] **Step 4: Verify Django check passes**

```bash
cd gateway && python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Run the full test suite**

```bash
cd gateway && python -m pytest tests/ -x -q
```

Expected: all passing, no failures.

- [ ] **Step 6: Commit**

```bash
git add gateway/api/v1/views/__init__.py gateway/api/v1/urls.py
git commit -m "delete programs ViewSet and remove router registration"
```
