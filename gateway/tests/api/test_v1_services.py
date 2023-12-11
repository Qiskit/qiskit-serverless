import json
from rest_framework.test import APITestCase
from api.exceptions import ResourceNotFoundException
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

    def test_find_one_program_by_title(self):
        """The test must return one Program filtered by specific title."""

        user = User.objects.get(id=1)
        title = "Program"

        program = ProgramService.find_one_by_title(title, user)

        self.assertIsNotNone(program)
        self.assertEqual(program.title, title)

    def test_fail_to_find_program_by_title(self):
        """The test must raise a 404 exception when we don't find a Program with a specific title."""

        user = User.objects.get(id=1)
        title = "This Program doesn't exist"

        with self.assertRaises(ResourceNotFoundException):
            ProgramService.find_one_by_title(title, user)
