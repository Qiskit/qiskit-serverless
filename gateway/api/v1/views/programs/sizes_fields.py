"""Shared read-only serializer fields for a function's size catalog.

The size catalog is not a plain column on ``Program``: the labels live in the
related ``FunctionSize`` table and ``default_size`` is a foreign key whose raw
form is an internal UUID. These fields render the catalog the way a caller wants
to read it, so it can ride along in the function representation instead of
needing a separate request.
"""

from rest_framework import serializers


class SizesFieldsMixin(serializers.Serializer):  # pylint: disable=abstract-method
    """Adds read-only ``sizes`` and ``default_size`` to a Program serializer.

    ``sizes`` is ``{label: compute_profile_id}`` for every declared size;
    ``default_size`` is the default size's label, or null when none is set.
    """

    sizes = serializers.SerializerMethodField()
    default_size = serializers.SerializerMethodField()

    def get_sizes(self, program) -> dict:
        """Return the declared catalog as ``{label: compute_profile_id}``."""
        return {size.function_size: size.compute_profile_id for size in program.function_sizes.all()}

    def get_default_size(self, program):
        """Return the default size's label, or None when the function has no default."""
        return program.default_size.function_size if program.default_size_id else None
