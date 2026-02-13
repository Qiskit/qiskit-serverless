"""Utilities for tests."""

from typing import Union

from django.contrib.auth.models import User, Group
from rest_framework.test import APIClient

from api.models import Job, Program, Provider


class TestUtils:
    """Utility class to provide helper methods for gateway testing."""

    @staticmethod
    def _get_user_and_username(author: Union[User, str]) -> tuple[User, str]:
        """Helper to normalize author input into (User object, username string)."""
        if isinstance(author, User):
            return author, author.username

        # If it's a string, get or create the user
        user, _ = User.objects.get_or_create(username=author)
        return user, author

    @staticmethod
    def _get_or_create_provider(provider_admin: str) -> Provider:
        """Helper to setup a provider and its admin group/user safely."""
        provider, _ = Provider.objects.get_or_create(
            name=provider_admin
        )  # provider name is unique
        # Setup Groups and Admin User if needed
        admin_group, _ = Group.objects.get_or_create(name=provider_admin)
        admin_user, _ = User.objects.get_or_create(username=provider_admin)

        if not admin_user.groups.filter(id=admin_group.id).exists():
            admin_user.groups.add(admin_group)

        # Associate group with provider
        if not provider.admin_groups.filter(id=admin_group.id).exists():
            provider.admin_groups.add(admin_group)

        return provider

    @staticmethod
    def create_program(
        author: Union[User, str] = "default_user",
        provider_admin: str = None,
        program_title: str = None,
        **kwargs,
    ) -> Program:
        """
        Creates a Program instance along with its dependencies (User, Provider).
        Args:
            author: The author or username for the Job (and Program).
            provider_admin: Optional username for the provider admin.
            program_title: Optional title. Defaults to author-provider format.
            **kwargs: Additional fields to set on the Program model
        """

        author_obj, author_username = TestUtils._get_user_and_username(author)
        provider = None

        if provider_admin:
            provider = TestUtils._get_or_create_provider(provider_admin)

        if not program_title:
            program_title = f"{author_username}-{provider_admin or 'custom'}"

        return Program.objects.create(
            title=program_title, author=author_obj, provider=provider, **kwargs
        )

    @staticmethod
    def create_job(
        author: Union[User, str] = "default_user",
        provider_admin: str = None,
        program: Program = None,
        program_title: str = None,
        **kwargs,
    ) -> Job:
        """
        Creates a Job instance along with its dependencies (User, Provider, Program).
        Args:
            author: The author or username for the Job (and Program).
            provider_admin: Optional admin for the linked Program.
            program: Optional Program instance.
            program_title: Optional title for the linked Program.
            **kwargs: Fields for the Job.
                     Use the key 'program_fields' (dict) to pass kwargs to the Program.
        """
        author_obj, _ = TestUtils._get_user_and_username(author)
        program_kwargs = kwargs.pop("program_fields", {})  # .pop() removes the key
        if not isinstance(program, Program):
            program = TestUtils.create_program(
                author=author,
                provider_admin=provider_admin,
                program_title=program_title,
                **program_kwargs,
            )

        return Job.objects.create(author=author_obj, program=program, **kwargs)

    @staticmethod
    def authorize_client(username: str, client: APIClient) -> User:
        """
        Helper to authenticate a DRF test client.
        """
        user, _ = User.objects.get_or_create(username=username)
        client.force_authenticate(user=user)
        return user
