"""Create compute resource command."""

from django.core.management.base import BaseCommand

from core.models import ComputeResource


class Command(BaseCommand):
    """Create compute resource command."""

    help = "Creates default compute resource."

    def add_arguments(self, parser):
        parser.add_argument("host", type=str, help="Host of compute resource.")

    def handle(self, *args, **options):
        host = options.get("host")
        compute_resource = ComputeResource(title="Ray cluster default", host=host)
        compute_resource.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully created compute resource {compute_resource.title}"
            )
        )
