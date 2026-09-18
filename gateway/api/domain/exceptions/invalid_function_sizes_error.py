"""Invalid function sizes error."""


class InvalidFunctionSizesError(ValueError):
    """Raised when a declared size catalog is malformed.

    A plain ``ValueError`` subclass rather than a DRF or Django exception so this
    module stays free of framework imports; each caller translates it into the
    error type its own layer returns.
    """
