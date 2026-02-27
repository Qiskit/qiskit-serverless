"""Provider not found exception."""

from api.domain.exceptions.not_found_exception import NotFoundError


class ProviderNotFoundException(NotFoundError):
    """Exception raised when a provider is not found."""

    def __init__(self, provider: str):
        self.provider = provider
        message = f"Provider {provider} doesn't exist."
        super().__init__(message)
