"""Custom function not entitled exception."""


class CustomFunctionNotEntitledException(Exception):
    """Raised when a user acts on a custom (provider-less) function without the entitlement to do so.

    Kept distinct from FunctionNotFoundException: a user working in their own
    namespace has no other owner's existence to hide, so the real cause -- a missing
    custom-functions entitlement -- is named outright and mapped to 403 rather than a
    misleading 404 'doesn't exist'.
    """

    # (verb for the "entitled to {verb}" clause, past participle for "could not be {...}")
    UPLOAD = ("upload", "uploaded", "function-custom.write")
    RUN = ("run", "run", "function-custom.run")

    def __init__(self, title: str, operation: tuple[str, str, str]):
        """
        Args:
            title: the function title the user tried to act on.
            operation: one of the class constants (UPLOAD, RUN) carrying the verb,
                its past participle, and the platform permission to name.
        """
        verb, past_participle, permission = operation
        self.title = title
        self.permission = permission
        message = (
            f"Your account is not entitled to {verb} custom Qiskit Functions, so "
            f"'{title}' could not be {past_participle}. Contact your administrator to "
            f"enable the '{permission}' permission for your account."
        )
        self.message = message
        super().__init__(message)
