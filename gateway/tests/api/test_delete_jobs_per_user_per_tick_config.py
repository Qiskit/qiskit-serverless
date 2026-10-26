"""Tests for the 0081 deletion of the scheduler.fleets.jobs_per_user_per_tick Config row."""

import importlib

import pytest
from django.apps import apps

from core.models import Config

delete_config = importlib.import_module("api.migrations.0081_delete_fleets_jobs_per_user_per_tick_config").delete_config


@pytest.mark.django_db
def test_delete_config_removes_only_the_old_per_user_per_tick_row():
    Config.objects.create(name="scheduler.fleets.jobs_per_user_per_tick", value="5", description="old")
    Config.objects.create(name="scheduler.fleets.jobs_per_tick", value="5", description="new")

    delete_config(apps, None)

    assert not Config.objects.filter(name="scheduler.fleets.jobs_per_user_per_tick").exists()
    assert Config.objects.filter(name="scheduler.fleets.jobs_per_tick").exists()
