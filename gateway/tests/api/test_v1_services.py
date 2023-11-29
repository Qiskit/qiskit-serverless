import json
from rest_framework.test import APITestCase
from api.v1.services import ProgramService
from api.v1.serializers import ProgramSerializer
from api.models import Program
from django.contrib.auth.models import User


class ServicesTest(APITestCase):
    """Tests for V1 services."""

    fixtures = ["tests/fixtures/fixtures.json"]

    def test_save_program(self):
        """Test to verify that the service creates correctly an entry with its serializer."""

        user = User.objects.get(id=1)
        data = '{"title": "My Qiskit Pattern", "entrypoint": "pattern.py"}'
        program_serializer = ProgramSerializer(data=json.loads(data))
        program_serializer.is_valid()

        program = ProgramService.save(program_serializer, user, "path")
        entry = Program.objects.get(id=program.id)

        self.assertIsNotNone(entry)
        self.assertEqual(program.title, entry.title)
