from qiskit_serverless import ServerlessError


class PartnerError(ServerlessError):
    """Custom error class from a partner that inherits from ServerlessError."""


# This is not a custom function example.
# This is a test code that is injected into a main.tmpl
# simulating provider functions execution.
class Runner:
    def run(self, arguments):
        raise PartnerError("A123", "My error message", {"my-args": 123})
