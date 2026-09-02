"""Domain rules for the function size catalog declared at upload time.

A function declares its sizes as a mapping of size label to compute profile
identifier, e.g. ``{"m": "16x128", "XL": "80x1280x8a100"}``, where the value
names an existing ``ComputeProfile`` row. This module owns the shape and the
naming rules for that mapping; whether a profile actually exists is a database
question and is answered in the use case, per ``specs/VIEWS.md``.

A size label is a user-facing name, so it is compared case-insensitively: an
uploader writing ``"XL"`` and a client running ``" xl "`` mean the same size.
Canonicalising through ``normalize_function_size`` keeps the
``unique_function_size`` constraint meaningful and keeps the upload path and the
run path agreeing on which sizes a function declares. ``casefold()`` rather than
``lower()`` so non-ASCII labels fold correctly.

Rows created directly in the admin backoffice bypass this module, since the
admin runs no API validation. A label typed there with different casing is a
distinct row that will not resolve at run time, so it should be entered in its
normalised form.
"""

from api.domain.exceptions.invalid_function_sizes_error import InvalidFunctionSizesError

# A size catalog is a hand written menu of machine shapes, so single digits are
# the norm and this only exists to stop a caller from turning one upload into an
# unbounded number of rows and profile lookups.
MAX_SIZES_PER_FUNCTION = 32

# Long enough for a descriptive label, and bounded by FunctionSize.function_size
# (CharField(max_length=64)) so an over-long name is refused with a 400 here
# rather than a database error on save.
MAX_SIZE_NAME_LENGTH = 64

# Bounded by ComputeProfile.compute_profile_id (CharField(max_length=255)), for
# the same reason.
MAX_COMPUTE_PROFILE_ID_LENGTH = 255


def normalize_function_size(function_size: str | None) -> str | None:
    """Return the canonical form of one size label, or None when absent."""
    if function_size is None:
        return None
    return function_size.strip().casefold()


def parse_function_sizes(sizes) -> dict[str, str]:
    """Validate a declared size catalog and return it with labels normalised.

    Args:
        sizes: the raw ``sizes`` value from an upload request.

    Returns:
        The mapping with every label normalised and every value stripped.

    Raises:
        InvalidFunctionSizesError: when the value is not a mapping of non-empty
            label to non-empty compute profile identifier, when it declares more
            than ``MAX_SIZES_PER_FUNCTION`` sizes, or when two labels collide
            once normalised (e.g. ``"XL"`` and ``"xl"``), which would otherwise
            silently drop one of them.
    """
    if not isinstance(sizes, dict):
        raise InvalidFunctionSizesError(
            "'sizes' should be an object mapping a size name to a compute profile, e.g. {'m': '16x128'}."
        )
    if not sizes:
        raise InvalidFunctionSizesError("'sizes' should declare at least one size.")
    if len(sizes) > MAX_SIZES_PER_FUNCTION:
        raise InvalidFunctionSizesError(
            f"'sizes' declares {len(sizes)} sizes and the maximum is {MAX_SIZES_PER_FUNCTION}."
        )

    parsed: dict[str, str] = {}
    for raw_name, raw_profile in sizes.items():
        if not isinstance(raw_name, str) or not isinstance(raw_profile, str):
            raise InvalidFunctionSizesError("'sizes' names and compute profiles should both be strings.")

        name = normalize_function_size(raw_name)
        profile = raw_profile.strip()
        if not name or not profile:
            raise InvalidFunctionSizesError("'sizes' names and compute profiles should both be non-empty.")
        if len(name) > MAX_SIZE_NAME_LENGTH:
            raise InvalidFunctionSizesError(
                f"Size name '{raw_name}' is longer than the maximum of {MAX_SIZE_NAME_LENGTH} characters."
            )
        if len(profile) > MAX_COMPUTE_PROFILE_ID_LENGTH:
            raise InvalidFunctionSizesError(
                f"Compute profile for size '{raw_name}' is longer than "
                f"the maximum of {MAX_COMPUTE_PROFILE_ID_LENGTH} characters."
            )
        if name in parsed:
            raise InvalidFunctionSizesError(
                f"'sizes' declares '{name}' more than once; size names are case-insensitive."
            )

        parsed[name] = profile

    return parsed
