from qiskit_serverless import ServerlessError


# This is not a custom function example.
# This is a test code that is inyected into a main.tmpl
# simulating provider functions execution.
class Runner:
    def run(self, arguments):
        raise ServerlessError("A123", "My error message", {"my-args": 123})
