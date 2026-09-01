"""Use case: upload (create or update) a Qiskit Function."""

import json
import logging

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import transaction
from rest_framework.exceptions import ValidationError as DRFValidationError

from api.access_policies.programs import ProgramAccessPolicies
from api.access_policies.providers import ProviderAccessPolicy
from api.domain.exceptions.function_configuration_exception import FunctionConfigurationException
from api.domain.exceptions.function_not_found_exception import FunctionNotFoundException
from api.domain.function_sizes import normalize_function_size, parse_function_sizes
from api.use_cases.programs.upload_input import UploadFunctionInput
from core.domain.authorization.function_access_result import FunctionAccessResult
from core.models import (
    CodeEngineProject,
    ComputeProfile,
    DEFAULT_PROGRAM_ENTRYPOINT,
    FunctionSize,
    Program as Function,
    Provider,
)
from core.utils import encrypt_env_vars

logger = logging.getLogger("api.api.use_cases.programs.upload")


def _normalize_dependency(raw_dependency) -> str:
    if isinstance(raw_dependency, str):
        return raw_dependency

    dependency_name = list(raw_dependency.keys())[0]
    dependency_version = str(list(raw_dependency.values())[0])

    try:
        if int(dependency_version[0]) >= 0:
            dependency_version = f"=={dependency_version}"
    except ValueError:
        pass

    return dependency_name + dependency_version


def _no_ce_project_message(function: Function) -> str:
    """Message for a Fleets function with no Code Engine project, naming its provider if it has one.

    Distinguishes a provider with no project linked at all from one whose linked project
    is inactive, since those call for different administrator action.
    """
    if function.provider:
        project = function.provider.code_engine_project
        if project and not project.active:
            return (
                f"Code Engine project '{project.project_name}' assigned to provider "
                f"'{function.provider.name}' is not active. Contact administrator."
            )
        return f"No active Code Engine project for provider '{function.provider.name}'. Contact administrator."
    return "No active Code Engine project available. Contact administrator."


def _resolve_compute_profiles(sizes: dict[str, str]) -> dict[str, ComputeProfile]:
    """Map each declared size name to its ComputeProfile row.

    Raises DRFValidationError (400) naming the first identifier with no row, so
    a typo is refused at upload time rather than failing every later run of the
    function inside the runner.
    """
    profiles = {}
    for name, compute_profile_id in sizes.items():
        profile = ComputeProfile.objects.get_by_id(compute_profile_id)
        if profile is None:
            raise DRFValidationError(
                f"Unknown compute profile '{compute_profile_id}' for size '{name}'. "
                "Contact an administrator to have it registered."
            )
        profiles[name] = profile
    return profiles


def _replace_function_sizes(function: Function, sizes: dict[str, str]) -> dict[str, FunctionSize]:
    """Replace a function's whole size catalog with ``sizes``.

    Every profile is resolved before anything is written, so a bad identifier
    leaves the stored catalog untouched. Names are normalized here so a caller
    other than the serializer cannot write rows that never match at run time.
    """
    sizes = parse_function_sizes(sizes)
    profiles = _resolve_compute_profiles(sizes)

    rows = {}
    for name, profile in profiles.items():
        row, _ = FunctionSize.objects.update_or_create(
            function=function,
            function_size=name,
            defaults={"compute_profile": profile},
        )
        rows[name] = row

    # Clear default_size before deleting, so a default that points at a removed
    # size does not depend on the FK's SET_NULL to be cleaned up.
    if function.default_size_id and function.default_size.function_size not in rows:
        function.default_size = None
        function.save(update_fields=["default_size"])

    FunctionSize.objects.function_sizes(function).exclude(function_size__in=list(rows)).delete()
    return rows


def _apply_default_size(function: Function, default_size: str) -> None:
    """Point ``function.default_size`` at one of its own declared sizes.

    Validated against what is stored now, which is why this runs after the
    catalog has been replaced: a request sending both fields means the new
    default refers to the new catalog. The name is normalized before lookup.
    """
    default_size = normalize_function_size(default_size)
    row = FunctionSize.objects.get_function_size(function, default_size)
    if row is None:
        available = sorted(FunctionSize.objects.function_sizes(function).values_list("function_size", flat=True))
        raise DRFValidationError(
            f"'default_size' is '{default_size}', which is not one of this function's sizes: "
            + (", ".join(available) if available else "this function declares no sizes.")
        )
    function.default_size = row
    function.save(update_fields=["default_size"])


class UploadFunctionUseCase:
    """Use case for uploading (creating or updating) a Qiskit Function."""

    def execute(
        self,
        user: AbstractUser,
        accessible_functions: FunctionAccessResult,
        data: UploadFunctionInput,
    ) -> Function:
        """Create or update a Qiskit Function.

        Raises FunctionNotFoundException when the user lacks permission.
        """
        provider_obj = None
        if data.provider:
            provider_obj = Provider.objects.filter(name=data.provider).first()
            if provider_obj is None:
                raise FunctionNotFoundException(function=data.title, provider=data.provider)
            existing = Function.objects.filter(title=data.title, provider__name=data.provider).first()
            if not ProviderAccessPolicy.can_upload_function(user, provider_obj, data.title, accessible_functions):
                raise FunctionNotFoundException(function=data.title, provider=data.provider)
        else:
            if not ProgramAccessPolicies.can_create(user, accessible_functions):
                raise FunctionNotFoundException(function=data.title, provider=None)
            existing = Function.objects.filter(title=data.title, author=user).first()

        if existing is None:
            return self._create(data, user=user, provider=provider_obj)
        return self._update(existing, data, user=user)

    def _create(self, data: UploadFunctionInput, user, provider) -> Function:
        logger.info("user_id=%s program=%s | Creating function", user.id, data.title)

        if data.entrypoint is None and data.image is None:
            raise FunctionConfigurationException("At least one of attributes (entrypoint, image) is required.")

        # Unlike an update, a new function has no stored catalog to fall back on, so
        # 'sizes' and 'default_size' must be declared together or not at all: one
        # without the other is either ambiguous (which of several sizes is default?)
        # or meaningless (default pointing at a catalog that does not exist yet).
        if data.sizes is not None and data.default_size is None:
            raise DRFValidationError("'default_size' is required when 'sizes' is provided.")
        if data.default_size is not None and data.sizes is None:
            raise DRFValidationError("'sizes' is required when 'default_size' is provided.")

        env_vars = data.env_vars
        if env_vars:
            env_vars = json.dumps(encrypt_env_vars(json.loads(env_vars)))

        raw_deps = json.loads(data.dependencies or "[]")
        dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])

        function = Function(
            title=data.title,
            author=user,
            provider=provider,
            runner=data.runner or Function.RAY,
            entrypoint=data.entrypoint or DEFAULT_PROGRAM_ENTRYPOINT,
            artifact=data.artifact,
            image=data.image,
            env_vars=env_vars or {},
            dependencies=dependencies,
            description=data.description,
            version=data.version,
        )
        if data.type is not None:
            function.type = data.type
        if data.arguments_schema is not None:
            function.arguments_schema = data.arguments_schema

        CodeEngineProject.objects.assign_to_program(function)
        if function.runner == Function.FLEETS and not function.code_engine_project:
            message = _no_ce_project_message(function)
            logger.warning("user_id=%s program=%s | %s", user.id, function.title, message)
            raise FunctionConfigurationException(message)

        # atomic() so all these writes commit together or not at all: the function
        # row must exist before a FunctionSize can reference it, and default_size
        # needs a second save for a UUID that did not exist at the first. Without
        # it, a size naming an unregistered profile returns 400 with the function
        # already committed and sizeless.
        with transaction.atomic():
            function.save()
            if data.sizes is not None:
                _replace_function_sizes(function, data.sizes)
                # data.default_size is guaranteed non-None here (checked above), so
                # there is nothing to infer, unlike the update path below.
                _apply_default_size(function, data.default_size)
            else:
                self._seed_default_size(function)
        return function

    def _apply_declared_default(self, function: Function, data: UploadFunctionInput) -> None:
        """Set the default size the uploader named, or infer it when unambiguous.

        Only reachable from ``_update``, where ``sizes`` can be sent without
        ``default_size``; ``_create`` requires both together and applies
        ``default_size`` directly.
        """
        if data.default_size is not None:
            _apply_default_size(function, data.default_size)
        elif len(data.sizes) == 1:
            # A single declared size is unambiguously the default; with several,
            # default_size stays unset and runs fall back to DEFAULT_COMPUTE_PROFILE.
            _apply_default_size(function, next(iter(data.sizes)))

    def _seed_default_size(self, function: Function) -> None:
        """Give a function with no declared catalog the deployment's default size.

        Declaring sizes is still optional, so this is what gets every function to
        a size. The seed is skipped rather than fatal when the profile row is
        absent (an operator may not have populated ComputeProfile yet), leaving
        the function to run on DEFAULT_COMPUTE_PROFILE as it did before sizes
        existed.
        """
        compute_profile_id = settings.DEFAULT_FUNCTION_SIZE_PROFILE
        profile = ComputeProfile.objects.get_by_id(compute_profile_id)
        if profile is None:
            logger.warning(
                "program=%s | Default compute profile [%s] is not registered; "
                "function created with no sizes and will run on the default compute profile.",
                function.title,
                compute_profile_id,
            )
            return

        size_name = settings.DEFAULT_FUNCTION_SIZE
        row = FunctionSize.objects.create(
            function=function,
            function_size=size_name,
            compute_profile=profile,
        )
        function.default_size = row
        function.save(update_fields=["default_size"])

    @staticmethod
    def _apply_scalar_updates(instance: Function, data: UploadFunctionInput) -> None:
        """Copy the simple pass-through fields the request provided onto ``instance``.

        Only fields sent (not None) overwrite; the rest keep their stored value.
        Kept separate from :meth:`_update` so that method stays under pylint's
        branch limit and the size/runner handling reads on its own.
        """
        for field in ("entrypoint", "artifact", "image", "description", "version", "arguments_schema"):
            value = getattr(data, field)
            if value is not None:
                setattr(instance, field, value)

    def _update(self, instance: Function, data: UploadFunctionInput, user) -> Function:
        logger.info("user_id=%s program=%s | Updating function", user.id, instance.title)

        self._apply_scalar_updates(instance, data)

        # dependencies and env_vars are transformed rather than copied verbatim.
        if data.dependencies is not None:
            raw_deps = json.loads(data.dependencies)
            instance.dependencies = json.dumps([_normalize_dependency(d) for d in raw_deps])
        if data.env_vars is not None:
            instance.env_vars = json.dumps(encrypt_env_vars(json.loads(data.env_vars)))
        if data.runner is not None:
            instance.runner = data.runner
            CodeEngineProject.objects.assign_to_program(instance)
            if instance.runner == Function.FLEETS and not instance.code_engine_project:
                message = _no_ce_project_message(instance)
                logger.warning("user_id=%s program=%s | %s", user.id, instance.title, message)
                raise FunctionConfigurationException(message)

        # atomic() so a failure mid-replacement cannot leave the old and new sizes
        # stored at once (the unique constraint does not catch it, the names
        # differ), and so a concurrent run cannot resolve a size in the window
        # between its replacement and its deletion.
        with transaction.atomic():
            instance.save()
            # Order matters: sizes first, so a request sending both fields
            # validates default_size against the catalog it just declared. Sent
            # alone, default_size matches against the stored sizes. Sizes are
            # never re-seeded here: a removed size should not reappear.
            if data.sizes is not None:
                _replace_function_sizes(instance, data.sizes)
            if data.default_size is not None:
                _apply_default_size(instance, data.default_size)
            elif data.sizes is not None:
                self._apply_declared_default(instance, data)
        return instance
