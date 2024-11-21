from django.db.models import Q
from django.contrib.auth.models import Group, Permission

from api.models import RUN_PROGRAM_PERMISSION, VIEW_PROGRAM_PERMISSION, Program


class ProgramRepository:
    def get_functions(self, author):
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        user_criteria = Q(user=author)
        view_permission_criteria = Q(permissions=view_program_permission)

        author_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )
        # author_groups_with_view_permissions_count = (
        #     author_groups_with_view_permissions.count()
        # )
        # logger.info(
        #     "ProgramViewSet get author [%s] groups [%s]",
        #     author.id,
        #     author_groups_with_view_permissions_count,
        # )

        author_criteria = Q(author=author)
        author_groups_with_view_permissions_criteria = Q(
            instances__in=author_groups_with_view_permissions
        )

        result_queryset = Program.objects.filter(
            author_criteria | author_groups_with_view_permissions_criteria
        ).distinct()
        return result_queryset

    def get_user_functions(self, author):
        author_criteria = Q(author=author)
        provider_criteria = Q(provider=None)

        user_functions = Program.objects.filter(
            author_criteria & provider_criteria
        ).distinct()

        # user_functions_count = user_functions.count()
        # logger.info(
        #     "ProgramViewSet get author [%s] programs [%s]",
        #     author.id,
        #     user_functions_count,
        # )

        return user_functions

    def get_provider_functions_with_run_permissions(self, author):
        run_program_permission = Permission.objects.get(codename=RUN_PROGRAM_PERMISSION)

        user_criteria = Q(user=author)
        run_permission_criteria = Q(permissions=run_program_permission)
        author_groups_with_run_permissions = Group.objects.filter(
            user_criteria & run_permission_criteria
        )
        # author_groups_with_run_permissions_count = (
        #     author_groups_with_run_permissions.count()
        # )
        # logger.info(
        #     "ProgramViewSet get author [%s] groups [%s]",
        #     author.id,
        #     author_groups_with_run_permissions_count,
        # )

        author_groups_with_run_permissions_criteria = Q(
            instances__in=author_groups_with_run_permissions
        )

        provider_exists_criteria = ~Q(provider=None)

        result_queryset = Program.objects.filter(
            author_groups_with_run_permissions_criteria & provider_exists_criteria
        ).distinct()
        return result_queryset

    def get_user_function_by_title(self, author, title: str):
        author_criteria = Q(author=author)
        title_criteria = Q(title=title)

        result_queryset = Program.objects.filter(
            author_criteria & title_criteria
        ).first()

        return result_queryset

    def get_provider_function_by_provider_and_title(
        self, author, title: str, provider_name: str
    ):
        view_program_permission = Permission.objects.get(
            codename=VIEW_PROGRAM_PERMISSION
        )

        user_criteria = Q(user=author)
        view_permission_criteria = Q(permissions=view_program_permission)

        author_groups_with_view_permissions = Group.objects.filter(
            user_criteria & view_permission_criteria
        )
        # author_groups_with_view_permissions_count = (
        #     author_groups_with_view_permissions.count()
        # )
        # logger.info(
        #     "ProgramViewSet get author [%s] groups [%s]",
        #     author.id,
        #     author_groups_with_view_permissions_count,
        # )

        author_groups_with_view_permissions_criteria = Q(
            instances__in=author_groups_with_view_permissions
        )

        title_criteria = Q(title=title, provider__name=provider_name)

        result_queryset = Program.objects.filter(
            author_groups_with_view_permissions_criteria & title_criteria
        ).first()

        return result_queryset

    def user_has_view_access(self):
        pass

    def user_has_run_access(self):
        pass
