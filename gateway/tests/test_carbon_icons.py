"""Verify that api/static shadows django.contrib.admin icons."""

from django.contrib.staticfiles.finders import find


def test_api_icons_shadow_django_admin():
    """Carbon icons in api/static must resolve before Django's built-in ones."""
    path = find("admin/img/icon-addlink.svg")
    assert path is not None, "icon-addlink.svg not found"
    assert "api" in path, (
        f"icon-addlink.svg resolved to {path!r}, " "expected it to come from api/static (check INSTALLED_APPS order)"
    )
