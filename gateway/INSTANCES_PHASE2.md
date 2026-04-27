# Fase 2 — FunctionAccessClient con permissions granulares

## Prerequisito

Fase 1 completada: todos los access checks centralizados en `ProviderAccessPolicy` y
`JobAccessPolicies`. No hay duplicados inline.

---

## Plan de PRs

La implementacion se divide en 5 PRs pequenos e independientes:

```
PR 1: Infraestructura nueva (sin tocar codigo existente)
    └── PR 2: Access policies + model manager
            ├── PR 3: Use cases + v1 views de jobs
            ├── PR 4: Use cases + v1 views de files
            └── PR 5: api/views/programs.py + serializer
```

| PR | Alcance | Riesgo |
|----|---------|--------|
| **PR 1** | `FunctionAccessEntry`, `FunctionAccessResult`, `FunctionAccessClient`, constantes `PLATFORM_PERMISSION_*` | Zero — solo adiciones |
| **PR 2** | `ProviderAccessPolicy`, `JobAccessPolicies`, `with_permission`, `get_function_by_permission` | Bajo — tests existentes actualizados |
| **PR 3** | Use cases + v1 views de jobs (retrieve, provider_logs, provider_list) | Medio — 3 flows de jobs |
| **PR 4** | Use cases + v1 views de files (user + provider, 8 use cases + 8 vistas) | Medio — files |
| **PR 5** | `api/views/programs.py` (list, upload, run, etc.) + `RunJobSerializer.create()` | Alto — toca `run()` y el serializer |

> En PR 2, los parametros `accessible_functions` y `action` se añaden como `Optional` con default
> `None` (internamente tratado como `FunctionAccessResult(has_response=False)`). Esto permite
> mergear PR 2 sin romper callers que aun no han sido actualizados. Los PRs 3-5 pasan el
> argumento explicitamente y en PR 5 (el ultimo) se puede hacer el parametro obligatorio
> si se desea.

---

## Objetivo

Introducir un cliente externo (`FunctionAccessClient`) que, dado un CRN de instancia,
devuelve la lista de funciones accesibles con **permissions granulares** por operacion.
El sistema actual de grupos Django se mantiene como fallback cuando el cliente no responde.

### Principio: Dual con fallback

```
request.auth.instance (CRN)
        |
        v
FunctionAccessClient.get_accessible_functions(crn)
        |
        |-- has_response=True  --> usar lista del cliente (autorizacion externa)
        |
        +-- has_response=False --> usar grupos Django (sistema actual, sin cambios)
```

### Cuando se consulta el cliente

Solo se consulta al cliente externo cuando la funcion a la que se accede **NO es del usuario**
(no es owner). Si el usuario es el author de la funcion (tanto serverless como de provider),
tiene acceso completo sin consultar al cliente. Esto es coherente con el comportamiento actual.

---

## Permissions de plataforma (PLATFORM_PERMISSION)

El cliente devuelve, por cada funcion, el conjunto de actions permitidos para esa instancia.
Se usa notacion de punto para agrupar por dominio. Los actions de ficheros se consolidan
en un unico action por ambito (usuario / provider), dado que no hay caso de uso para
permitir listar pero no descargar, o subir pero no borrar.

Los actions se definen como constantes en `core/models.py`, al mismo nivel que
`VIEW_PROGRAM_PERMISSION` y `RUN_PROGRAM_PERMISSION`:

```python
# Platform permissions (cliente externo de acceso por instancia)
PLATFORM_PERMISSION_VIEW = "view"
PLATFORM_PERMISSION_RUN = "run"
PLATFORM_PERMISSION_USER_FILES = "user.files"
PLATFORM_PERMISSION_PROVIDER_UPLOAD = "provider.upload"
PLATFORM_PERMISSION_PROVIDER_JOBS = "provider.jobs"
PLATFORM_PERMISSION_JOB_RETRIEVE = "job.retrieve"
PLATFORM_PERMISSION_PROVIDER_LOGS = "provider.logs"
PLATFORM_PERMISSION_PROVIDER_FILES = "provider.files"
```

### Tabla de actions

| Constante                          | Valor                 | Sustituye a...                          | Endpoints                                             |
|------------------------------------|-----------------------|-----------------------------------------|-------------------------------------------------------|
| **Acceso de usuario**              |                       |                                         |                                                       |
| `PLATFORM_PERMISSION_VIEW`             | `view`                | `view_program` permission + `instances` | `list` (catalog/all), `get_by_title`                  |
| `PLATFORM_PERMISSION_RUN`              | `run`                 | `run_program` permission + `instances`  | `run`                                                 |
| `PLATFORM_PERMISSION_USER_FILES`       | `user.files`          | `run_program` permission + `instances`  | `v1/files/` (list, download, upload, delete)          |
| **Acceso de provider**             |                       |                                         |                                                       |
| `PLATFORM_PERMISSION_PROVIDER_UPLOAD`  | `provider.upload`     | `admin_groups` intersection             | `upload` (provider function)                          |
| `PLATFORM_PERMISSION_PROVIDER_JOBS`    | `provider.jobs`       | `admin_groups` intersection             | `v1/jobs/provider`, `get_jobs` (deprecated)           |
| `PLATFORM_PERMISSION_JOB_RETRIEVE`     | `job.retrieve`        | `admin_groups` intersection             | `v1/jobs/<id>` (retrieve, solo non-author)            |
| `PLATFORM_PERMISSION_PROVIDER_LOGS`    | `provider.logs`       | `admin_groups` intersection             | `v1/jobs/<id>/provider-logs`                          |
| `PLATFORM_PERMISSION_PROVIDER_FILES`   | `provider.files`      | `admin_groups` (solo)                   | `v1/files/provider/` (list, download, upload, delete) |

> **Nota de diseño — provider files**: La implementacion anterior requeria `admin_groups` +
> `run_program` para gestionar ficheros de provider. Esto era un error de diseño: `run_program`
> es un permiso de consumidor (ejecutar la funcion), no de administrador. Un admin de provider
> deberia poder gestionar ficheros de cualquier funcion de su provider sin necesitar permiso de
> ejecucion. En el nuevo sistema, el action `provider.files` solo requiere ser admin del
> provider (o tener el action en el cliente externo). Se elimina el check de
> `get_function_by_permission(run_program)` para los use cases de provider files.

### Endpoints que NO necesitan consultar al cliente

Estos endpoints solo permiten acceso al autor del job. No hay rol de provider ni de usuario
externo, asi que no necesitan el cliente:

| Endpoint                    | Razon                                                 |
|-----------------------------|-------------------------------------------------------|
| `v1/jobs/` (list)           | Filtra por `author=user` en queryset                  |
| `v1/jobs/<id>/logs`         | Author only                                           |
| `v1/jobs/<id>/result`       | Author only                                           |
| `v1/jobs/<id>/stop`         | Author only (check añadido en Fase 1)                 |
| `v1/jobs/<id>/sub_status`   | Author only                                           |
| `v1/jobs/<id>/event`        | Author only                                           |
| `v1/jobs/<id>/events`       | Author only                                           |
| `v1/jobs/<id>/runtime_jobs` | Author only (check añadido en Fase 1)                 |
| `list` (serverless)         | Solo funciones propias (`author=user, provider=None`) |

---

## Especificacion de componentes

### 1. `FunctionAccessEntry`

**Fichero nuevo**: `api/domain/authorization/function_access_entry.py`

```python
import logging
from dataclasses import dataclass
from typing import Set

from core.models import Job

logger = logging.getLogger("api.FunctionAccessEntry")

VALID_BUSINESS_MODELS = {
    Job.BUSINESS_MODEL_TRIAL,
    Job.BUSINESS_MODEL_SUBSIDIZED,
    Job.BUSINESS_MODEL_CONSUMPTION,
}


@dataclass
class FunctionAccessEntry:
    provider_name: str     # Provider.name
    function_title: str    # Program.title
    permissions: Set[str]      # {PLATFORM_PERMISSION_RUN, PLATFORM_PERMISSION_VIEW, ...}
    business_model: str    # Job.BUSINESS_MODEL_TRIAL, BUSINESS_MODEL_SUBSIDIZED, etc.

    def __post_init__(self):
        if self.business_model not in VALID_BUSINESS_MODELS:
            logger.error(
                "Invalid business_model '%s' for %s.%s. Valid: %s",
                self.business_model, self.provider_name, self.function_title,
                VALID_BUSINESS_MODELS,
            )
            raise ValueError(
                f"Invalid business_model '{self.business_model}' "
                f"for {self.provider_name}.{self.function_title}"
            )
```

`provider_name` y `function_title` corresponden a `Provider.name` y `Program.title`.
El cliente externo devuelve estos dos campos por separado.
`business_model` solo es relevante cuando `PLATFORM_PERMISSION_RUN` esta en `actions`.
Se valida en `__post_init__` contra los choices de `Job` — un valor invalido lanza `ValueError`.

---

### 2. `FunctionAccessResult`

**Fichero nuevo**: `api/domain/authorization/function_access_result.py`

```python
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from api.domain.authorization.function_access_entry import FunctionAccessEntry


@dataclass
class FunctionAccessResult:
    has_response: bool
    functions: List[FunctionAccessEntry] = field(default_factory=list)

    def get_function(self, provider_name: str, function_title: str) -> Optional[FunctionAccessEntry]:
        """Devuelve la entrada para un provider_name + function_title, o None."""
        for entry in self.functions:
            if entry.provider_name == provider_name and entry.function_title == function_title:
                return entry
        return None

    def has_permission_for_provider(self, provider_name: str, permission: str) -> bool:
        """
        True si alguna funcion del provider dado tiene el action.
        Util para checks a nivel de provider (ProviderAccessPolicy).
        No necesita consultar la DB.
        """
        return any(
            e.provider_name == provider_name and permission in e.permissions
            for e in self.functions
        )

    def get_functions_by_provider(self, action: str) -> Dict[str, Set[str]]:
        """
        Agrupa por provider_name los function_titles que tengan el action.
        Util para construir querysets eficientes con IN.
        """
        by_provider: Dict[str, Set[str]] = defaultdict(set)
        for e in self.functions:
            if permission in e.permissions:
                by_provider[e.provider_name].add(e.function_title)
        return dict(by_provider)
```

---

### 3. `FunctionAccessClient`

**Fichero nuevo**: `api/clients/function_access_client.py`

```python
from abc import ABC, abstractmethod
from api.domain.authorization.function_access_result import FunctionAccessResult


class FunctionAccessClient:
    """Subclasear e implementar get_accessible_functions() con el servicio real.
    En tests, parchear el metodo directamente sobre la clase o instancia."""

    def get_accessible_functions(self, instance_crn: str) -> FunctionAccessResult:
        raise NotImplementedError
```

#### Patron en las vistas para obtener `accessible_functions`

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)
```

Este patron se repite en todas las vistas que necesitan el cliente.
En tests se parchea `FunctionAccessClient.get_accessible_functions` con `monkeypatch` o `unittest.mock.patch`.

---

### 4. `business_model` en `Job` — ya implementado

> **Estado**: El campo `business_model` ya existe en `Job` (`core/models.py`) como NOT NULL
> con choices `TRIAL`/`SUBSIDIZED`/`CONSUMPTION` y default `SUBSIDIZED`. Las migraciones
> (0047, 0048 backfill, 0049 not null) ya estan aplicadas. El metodo `RunJobSerializer.create()`
> ya calcula `business_model` desde `is_trial()` al crear jobs.

#### Que cambia en Fase 2

Cuando el cliente externo responde, se usa `entry.business_model` directamente en vez del
calculo actual con `is_trial()`. El campo `trial` se deriva de `business_model`:

- Si el cliente respondio: `business_model = entry.business_model`, `trial = (business_model == "TRIAL")`
- Si no (fallback): sin cambios, `is_trial()` calcula `trial` y de ahi se deriva `business_model`

No se necesita modificar `core/models.py` ni crear migraciones.

---

## Integraciones

### 5. `with_permission()` — listado de funciones

**Fichero a modificar**: `core/model_managers/functions.py`

Añadir parametros obligatorios `accessible_functions` y `action`:

```python
def with_permission(
        self,
        author: AbstractUser,
        legacy_permission_name: str,
        accessible_functions: "FunctionAccessResult",
        permission: str,
) -> Self:
    if accessible_functions.has_response:
        by_provider = accessible_functions.get_functions_by_provider(action)
        provider_criteria = Q()
        for pname, titles in by_provider.items():
            provider_criteria |= Q(provider__name=pname, title__in=titles)
        return self.filter(Q(author=author) | provider_criteria).distinct()

    # Fallback: sistema actual de grupos (sin cambios)
    groups = Group.objects.filter(user=author, permissions__codename=legacy_permission_name)
    author_groups_with_permissions_criteria = Q(instances__in=groups)
    author_criteria = Q(author=author)
    return self.filter(author_criteria | author_groups_with_permissions_criteria).distinct()
```

> Nota: cuando `has_response=True` y no hay entries con el action, `by_provider` queda
> vacio, `provider_criteria` queda vacio (`Q()`), y el filtro devuelve solo las funciones
> propias del usuario. No hace falta un check especial para "no entries".
> Se agrupa por provider para generar SQL eficiente con `IN` en vez de un OR por funcion.

Actualizar tambien `get_function_by_permission()`. `action` es **obligatorio** (no se mapea
desde `legacy_permission_name`, son sistemas de permisos distintos). Se usa `provider_name`
y `function_title` para buscar en `accessible_functions`:

```python
def get_function_by_permission(
        self,
        user,
        legacy_permission_name: str,
        function_title: str,
        provider_name: Optional[str],
        accessible_functions: "FunctionAccessResult",
        permission: str,
) -> Optional[Function]:
    if not provider_name:
        return self.user_functions(author=user).get_function(function_title)

    if accessible_functions.has_response:
        entry = accessible_functions.get_function(provider_name, function_title)
        if entry is None or permission not in entry.permissions:
            return None
        return self.get_function(function_title, provider_name)

    # Fallback: sistema actual de grupos (sin cambios)
    return self.with_permission(
        author=user,
        legacy_permission_name=legacy_permission_name,
        accessible_functions=accessible_functions,
        permission=permission,
    ).get_function(function_title, provider_name)
```

---

### 5b. Endpoint `list()`

**Fichero a modificar**: `api/views/programs.py` — metodo `list()`

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)

if type_filter == TypeFilter.SERVERLESS:
    functions = Function.objects.user_functions(author)
elif type_filter == TypeFilter.CATALOG:
    functions = Function.objects.provider_functions().with_permission(
        author,
        legacy_permission_name=RUN_PROGRAM_PERMISSION,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_RUN,
    )
else:
    functions = Function.objects.with_permission(
        author,
        legacy_permission_name=VIEW_PROGRAM_PERMISSION,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )
```

La rama `SERVERLESS` no cambia (solo devuelve funciones propias).

---

### 5c. Endpoint `upload()` — con action `PLATFORM_PERMISSION_PROVIDER_UPLOAD`

**Fichero a modificar**: `api/views/programs.py` — metodo `upload()`

El check ya fue centralizado en Fase 1 a usar `ProviderAccessPolicy.can_access()`.
Ahora le pasamos `accessible_functions` con el action:

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)

if provider_name:
    provider_obj = Provider.objects.filter(name=provider_name).first()
    if provider_obj is None or not ProviderAccessPolicy.can_access(
            user=author, provider=provider_obj,
            accessible_functions=accessible, permission=PLATFORM_PERMISSION_PROVIDER_UPLOAD,
    ):
        return Response(
            {"message": f"Provider [{provider_name}] was not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    program = serializer.retrieve_provider_function(title=title, provider_name=provider_name)
```

---

### 5d. Endpoint `get_jobs()` (deprecated) — con action `PLATFORM_PERMISSION_PROVIDER_JOBS`

**Fichero a modificar**: `api/views/programs.py` — metodo `get_jobs()`

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)

user_is_provider = False
if program.provider:
    user_is_provider = ProviderAccessPolicy.can_access(
        user=request.user,
        provider=program.provider,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_PROVIDER_JOBS,
    )
```

---

### 6. Endpoint `/run` — con action `PLATFORM_PERMISSION_RUN`

**Fichero a modificar**: `api/views/programs.py` — metodo `run()`

Despues de obtener `provider_name`, `function_title` y `author`, y **antes** del check:

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)

business_model = None

if accessible.has_response:
    if provider_name:
        entry = accessible.get_function(provider_name, function_title)
        if entry is None or PLATFORM_PERMISSION_RUN not in entry.permissions:
            return Response(
                {"message": f"Qiskit Pattern [{function_title}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        function = Function.objects.get_function(function_title, provider_name)
        if function is None:
            return Response(
                {"message": f"Qiskit Pattern [{function_title}] was not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        business_model = entry.business_model
    else:
        function = Function.objects.get_user_function(author, function_title)
else:
    function = Function.objects.get_function_by_permission(
        user=author,
        legacy_permission_name=RUN_PROGRAM_PERMISSION,
        function_title=function_title,
        provider_name=provider_name,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_RUN,
    )
```

Pasar `business_model` al serializer solo cuando tiene valor (evita fragilidad con `None`):

```python
save_kwargs = dict(
    author=author,
    carrier=carrier,
    channel=channel,
    token=token,
    config=jobconfig,
    instance=instance,
)
if business_model is not None:
    save_kwargs["business_model"] = business_model
job = job_serializer.save(**save_kwargs)
```

---

### 7. `RunJobSerializer.create()`

**Fichero a modificar**: `api/serializers.py` — `RunJobSerializer.create()`

El serializer ya calcula `business_model` desde `is_trial()`. Solo hay que añadir la rama
para cuando el cliente externo proporciona `business_model` directamente:

```python
def create(self, validated_data):
    program = validated_data.get("program")
    author = validated_data.get("author")
    # ...
    external_business_model = validated_data.pop("business_model", None)

    if external_business_model is not None:
        business_model = external_business_model
        trial = (business_model == Job.BUSINESS_MODEL_TRIAL)
    else:
        # Fallback: sistema actual de grupos (sin cambios)
        trial = self.is_trial(program, author)
        business_model = Job.BUSINESS_MODEL_TRIAL if trial else Job.BUSINESS_MODEL_SUBSIDIZED

    job = Job(
        trial=trial,
        business_model=business_model,
        # ...
    )
```

El metodo `is_trial()` no se modifica: sigue siendo el fallback.

---

### 8. `ProviderAccessPolicy` — metodos nombrados por operacion

**Fichero a modificar**: `api/access_policies/providers.py`

> **Cambio de diseño respecto al plan original**: en lugar de un metodo generico
> `can_access(permission=...)` donde el caller debia conocer la constante de permiso,
> se implementaron metodos nombrados por operacion. El permission es un detalle de
> implementacion interno; los callers solo declaran *que operacion* intentan hacer.

La logica compartida vive en un helper privado `_check`:

```python
@staticmethod
def _check(user, provider, accessible_functions, permission) -> bool:
    if accessible_functions is not None and accessible_functions.has_response:
        return accessible_functions.has_permission_for_provider(provider.name, permission)
    user_groups = set(user.groups.all())
    return bool(user_groups.intersection(set(provider.admin_groups.all())))
```

Los metodos publicos validan `provider is not None`, llaman a `_check` con la constante
de permiso correcta, y loguean si no hay acceso:

| Metodo                  | Permission interna                    |
|-------------------------|---------------------------------------|
| `can_retrieve_job`      | `PLATFORM_PERMISSION_JOB_RETRIEVE`    |
| `can_read_logs`         | `PLATFORM_PERMISSION_PROVIDER_LOGS`   |
| `can_list_jobs`         | `PLATFORM_PERMISSION_PROVIDER_JOBS`   |
| `can_manage_files`      | `PLATFORM_PERMISSION_PROVIDER_FILES`  |
| `can_upload_function`   | `PLATFORM_PERMISSION_PROVIDER_UPLOAD` |

Todos aceptan `accessible_functions: Optional[FunctionAccessResult] = None`.
Cuando es `None` o `has_response=False`, el fallback es identico para todos:
interseccion de grupos Django con `provider.admin_groups`.

---

### 9. `JobAccessPolicies` con `accessible_functions`

**Fichero a modificar**: `api/access_policies/jobs.py`

`can_access()` y `can_read_provider_logs()` llaman a los nuevos metodos nombrados
de `ProviderAccessPolicy` (ya no necesitan importar las constantes `PLATFORM_PERMISSION_*`):

```python
@staticmethod
def can_access(user, job, accessible_functions=None) -> bool:
    if user.id == job.author.id:
        return True
    has_access = False
    if job.program and job.program.provider:
        has_access = ProviderAccessPolicy.can_retrieve_job(
            user, job.program.provider, accessible_functions
        )
    # ...

@staticmethod
def can_read_provider_logs(user, job, accessible_functions=None) -> bool:
    if job.program.provider and ProviderAccessPolicy.can_read_logs(
        user, job.program.provider, accessible_functions
    ):
        return True
    # ...
```

---

### 10. Propagacion a use cases y vistas v1

El parametro `accessible_functions: FunctionAccessResult` es **obligatorio** en todos los
sitios donde se añade. Esto garantiza que no se pueda olvidar accidentalmente.

#### 10a. Patron en las vistas v1

En cada vista, obtener el CRN, llamar al cliente **una vez** y pasar el resultado:

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)
result = SomeUseCase().execute(user=user, ..., accessible_functions=accessible)
```

#### 10b. Use cases de provider (solo admin check)

Cada use case de provider recibe `accessible_functions` y lo pasa a `ProviderAccessPolicy`.
Los use cases de **ficheros de provider ya no usan `get_function_by_permission(run_program)`**
(ver nota de diseño en la tabla de actions). Solo verifican acceso de admin al provider y
que la funcion exista con `Function.objects.get_function(title, provider_name)`.

| Use case                       | Fichero                                       | Action para ProviderAccessPolicy     |
|--------------------------------|-----------------------------------------------|--------------------------------------|
| `JobsProviderListUseCase`      | `api/use_cases/jobs/provider_list.py`         | `PLATFORM_PERMISSION_PROVIDER_JOBS`      |
| `FilesProviderListUseCase`     | `api/use_cases/files/provider_list.py`        | `PLATFORM_PERMISSION_PROVIDER_FILES`     |
| `FilesProviderDownloadUseCase` | `api/use_cases/files/provider_download.py`    | `PLATFORM_PERMISSION_PROVIDER_FILES`     |
| `FilesProviderUploadUseCase`   | `api/use_cases/files/provider_upload.py`      | `PLATFORM_PERMISSION_PROVIDER_FILES`     |
| `FilesProviderDeleteUseCase`   | `api/use_cases/files/provider_delete.py`      | `PLATFORM_PERMISSION_PROVIDER_FILES`     |

**Codigo concreto para los use cases de ficheros de provider** (los 4 siguen el mismo patron):

```python
# Ejemplo: FilesProviderListUseCase (los demas son analogos)
def execute(self, user: AbstractUser, provider_name: str, function_title: str,
            accessible_functions: "FunctionAccessResult"):

    provider = self.provider_repository.get_provider_by_name(name=provider_name)
    if provider is None or not ProviderAccessPolicy.can_access(
        user=user, provider=provider,
        accessible_functions=accessible_functions,
        permission=PLATFORM_PERMISSION_PROVIDER_FILES,
    ):
        raise ProviderNotFoundException(provider_name)

    # CAMBIO: antes usaba get_function_by_permission(RUN_PROGRAM_PERMISSION).
    # Ahora solo verifica que la funcion exista (el acceso ya se valido arriba).
    function = Function.objects.get_function(
        function_title=function_title,
        provider_name=provider_name,
    )
    if not function:
        raise FunctionNotFoundException(function=function_title, provider=provider_name)

    # ... resto sin cambios (file_storage operations)
```

**`JobsProviderListUseCase`** sigue el mismo patron pero con `PLATFORM_PERMISSION_PROVIDER_JOBS`
y sin cambio en la busqueda de funcion (ya usaba `get_function()` sin permisos).

#### 10c. Use cases de usuario (solo function check)

| Use case               | Fichero                              | Action para get_function_by_permission |
|------------------------|--------------------------------------|----------------------------------------|
| `FilesListUseCase`     | `api/use_cases/files/list.py`        | `PLATFORM_PERMISSION_USER_FILES`           |
| `FilesDownloadUseCase` | `api/use_cases/files/download.py`    | `PLATFORM_PERMISSION_USER_FILES`           |
| `FilesUploadUseCase`   | `api/use_cases/files/upload.py`      | `PLATFORM_PERMISSION_USER_FILES`           |
| `FilesDeleteUseCase`   | `api/use_cases/files/delete.py`      | `PLATFORM_PERMISSION_USER_FILES`           |

#### 10d. Use cases de jobs (solo JobAccessPolicies)

| Use case                    | Fichero                                  | Metodo de JobAccessPolicies                                              |
|-----------------------------|------------------------------------------|--------------------------------------------------------------------------|
| `JobRetrieveUseCase`        | `api/use_cases/jobs/retrieve.py:34`      | `can_access()` (action=`PLATFORM_PERMISSION_JOB_RETRIEVE`)                   |
| `GetProviderJobLogsUseCase` | `api/use_cases/jobs/provider_logs.py:44` | `can_read_provider_logs()` (action=`PLATFORM_PERMISSION_PROVIDER_LOGS`)      |

#### 10e. `get_by_title()` en `api/views/programs.py`

```python
crn = getattr(request.auth, 'instance', None)
if crn:
    accessible = FunctionAccessClient().get_accessible_functions(crn)
else:
    accessible = FunctionAccessResult(has_response=False)

if provider_name:
    function = Function.objects.get_function_by_permission(
        user=author,
        legacy_permission_name=VIEW_PROGRAM_PERMISSION,
        function_title=function_title,
        provider_name=provider_name,
        accessible_functions=accessible,
        permission=PLATFORM_PERMISSION_VIEW,
    )
```

#### 10f. Tabla de vistas v1 a modificar

| Vista                     | Fichero                                   |
|---------------------------|-------------------------------------------|
| `get_provider_jobs`       | `api/v1/views/jobs/provider_list.py`      |
| `retrieve`                | `api/v1/views/jobs/retrieve.py`           |
| `provider_logs`           | `api/v1/views/jobs/provider_logs.py`      |
| `files_provider_list`     | `api/v1/views/files/provider_list.py`     |
| `files_provider_download` | `api/v1/views/files/provider_download.py` |
| `files_provider_upload`   | `api/v1/views/files/provider_upload.py`   |
| `files_provider_delete`   | `api/v1/views/files/provider_delete.py`   |
| `files_list`              | `api/v1/views/files/list.py`              |
| `files_download`          | `api/v1/views/files/download.py`          |
| `files_upload`            | `api/v1/views/files/upload.py`            |
| `files_delete`            | `api/v1/views/files/delete.py`            |

---

## Resumen de ficheros a crear/modificar

### Ficheros nuevos

| Fichero                                                | Descripcion                                  |
|--------------------------------------------------------|----------------------------------------------|
| `api/domain/authorization/__init__.py`               | Package init                                 |
| `api/domain/authorization/function_access_entry.py`  | Dataclass `FunctionAccessEntry`              |
| `api/domain/authorization/function_access_result.py` | Dataclass `FunctionAccessResult` con helpers |
| `api/clients/__init__.py`                              | Package init                                 |
| `api/clients/function_access_client.py`                | `FunctionAccessClient` (raises NotImplementedError) + factory |

### Ficheros a modificar

| Fichero                                    | Que cambia                                                                                                               |
|--------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| `core/models.py`                           | Añadir constantes `PLATFORM_PERMISSION_*`                                                                                    |
| `core/model_managers/functions.py`         | ✅ **PR2**: `with_permission()` y `get_function_by_permission()` implementados; imports restaurados a `TYPE_CHECKING` para evitar import circular |
| `core/domain/authorization/function_access_result.py` | ✅ **PR2 (bugfix)**: añadido `@dataclass` y `field(default_factory=list)` que faltaban |
| `api/views/programs.py`                    | ✅ **PR2**: `upload()` → `can_upload_function`, `get_jobs()` → `can_list_jobs`; PRs 3+: `list()`, `run()`, `get_by_title()` con CRN + cliente |
| `api/serializers.py`                       | `RunJobSerializer.create()`: aceptar y usar `business_model`                                                             |
| `api/access_policies/providers.py`         | ✅ **PR2**: reemplazado `can_access(permission=...)` con 5 metodos nombrados + helper privado `_check` |
| `api/access_policies/jobs.py`              | ✅ **PR2**: `can_access()` y `can_read_provider_logs()` usan `can_retrieve_job` / `can_read_logs`      |
| `api/use_cases/jobs/provider_list.py`      | ✅ **PR2**: actualizado a `can_list_jobs()` (sin `accessible_functions` aun; PRs 3+ lo añadiran)       |
| `api/use_cases/files/provider_download.py` | ✅ **PR2**: actualizado a `can_manage_files()` (sin `accessible_functions` aun)                        |
| `api/use_cases/files/provider_upload.py`   | ✅ **PR2**: actualizado a `can_manage_files()` (sin `accessible_functions` aun)                        |
| `api/use_cases/files/provider_delete.py`   | ✅ **PR2**: actualizado a `can_manage_files()` (sin `accessible_functions` aun)                        |
| `api/use_cases/files/provider_list.py`     | ✅ **PR2**: actualizado a `can_manage_files()` (sin `accessible_functions` aun)                        |
| `api/use_cases/jobs/retrieve.py`           | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/jobs/provider_logs.py`      | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/files/download.py`          | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/files/upload.py`            | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/files/delete.py`            | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/files/list.py`              | PRs 3+: añadir `accessible_functions` param                                                            |
| `api/use_cases/files/download.py`          | Añadir `accessible_functions` param                                                                                      |
| `api/use_cases/files/upload.py`            | Añadir `accessible_functions` param                                                                                      |
| `api/use_cases/files/delete.py`            | Añadir `accessible_functions` param                                                                                      |
| `api/use_cases/files/list.py`              | Añadir `accessible_functions` param                                                                                      |
| `api/v1/views/jobs/retrieve.py`            | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/jobs/provider_logs.py`       | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/jobs/provider_list.py`       | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/provider_download.py`  | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/provider_list.py`      | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/provider_upload.py`    | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/provider_delete.py`    | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/download.py`           | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/upload.py`             | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/list.py`               | Obtener CRN + pasar `accessible_functions`                                                                               |
| `api/v1/views/files/delete.py`             | Obtener CRN + pasar `accessible_functions`                                                                               |

---

## Verificacion

### Tests existentes que necesitan actualizacion

✅ **Completado en PR2**:

- `tests/api/access_policies/test_providers.py` — reescritos para los 5 metodos nombrados;
  eliminados los tests del antiguo `can_access(permission=...)`
- `tests/api/access_policies/test_jobs.py` — sin cambios de comportamiento; los tests
  existentes siguen cubriendo el flujo completo

### Tests nuevos para el flujo con cliente externo

En tests, parchear `FunctionAccessClient.get_accessible_functions` con datos controlados:

```python
# Con monkeypatch:
monkeypatch.setattr(FunctionAccessClient, "get_accessible_functions", lambda self, crn: FunctionAccessResult(has_response=True, functions=[entry]))

# Con unittest.mock.patch:
with patch.object(FunctionAccessClient, "get_accessible_functions", return_value=FunctionAccessResult(has_response=True, functions=[entry])):
    response = self.client.get(url)
```

Tests sugeridos:

- Test que con `has_response=True` y `PLATFORM_PERMISSION_RUN`, el usuario puede ejecutar la funcion
- Test que con `has_response=True` sin `PLATFORM_PERMISSION_RUN`, se devuelve 404
- Test que con `has_response=True` y `PLATFORM_PERMISSION_PROVIDER_UPLOAD`, el usuario puede subir una funcion
- Test que con `has_response=True` y `PLATFORM_PERMISSION_PROVIDER_LOGS`, el usuario puede ver provider logs
- Test que con `has_response=True` y `PLATFORM_PERMISSION_PROVIDER_FILES`, el admin puede listar/descargar ficheros de provider
- Test que con `has_response=True` y `PLATFORM_PERMISSION_USER_FILES`, el usuario puede listar/descargar ficheros
- Test que con `has_response=False`, todo funciona como antes (fallback a grupos)
- Test que `business_model` se guarda correctamente en el Job
- Test que `trial` se calcula desde `business_model` cuando esta disponible
- Test que `provider_name` + `function_title` en `FunctionAccessEntry` coinciden con `Provider.name` + `Program.title`

### Comandos

```bash
pytest tests/ -v
pytest --cov=api --cov=core --cov-report=term-missing --cov-fail-under=86 tests/
```