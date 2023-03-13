from django.contrib import admin
from .models import Job, Program, ComputeResource


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    pass


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    pass


@admin.register(ComputeResource)
class ComputeResourceAdmin(admin.ModelAdmin):
    pass
