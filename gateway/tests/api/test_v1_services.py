from rest_framework.test import APITestCase
from api.v1.services import ProgramService
from api.v1.serializers import ProgramSerializer


class ServicesTest(APITestCase):
    """Tests for V1 services."""

    def test_save_program(self):
        # data = '{"title": "My Qiskit Pattern", "entrypoint": "./pattern.py", "arguments": "", "dependencies": "[]", "env_vars": "{}"}'
        pass
