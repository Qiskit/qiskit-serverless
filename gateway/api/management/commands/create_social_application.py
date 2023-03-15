"""Create social app command."""

from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Create social app command."""

    help = "Creates keycloak social app and default site."

    def add_arguments(self, parser):
        parser.add_argument(
            "--host",
            type=str,
            help="Django site host. Also used for keycloak social app.",
        )
        parser.add_argument("--client_id", type=str, help="Keycloak client id.")

    def handle(self, *args, **options):
        host = options.get("host")
        client_id = options.get("client_id")

        if host is None or client_id is None:
            raise CommandError("Arguments [host] and [client_id] must be provided.")

        site = Site.objects.filter(domain=host).first()
        if site is None:
            site = Site(domain=host, name=host)
        site.save()

        social_app = SocialApp.objects.filter(provider="keycloak").first()
        if social_app is None:
            social_app = SocialApp(
                provider="keycloak", name="keycloak", client_id=client_id
            )
        social_app.save()
        social_app.sites.add(site)
        social_app.save()

        self.stdout.write(
            self.style.SUCCESS("Successfully created site and keycloak app.")
        )
