from qiskit_serverless import ServerlessError

raise ServerlessError("A123", "My error message", {"my-args": 123})
