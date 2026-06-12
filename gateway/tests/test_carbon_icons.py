"""Verifica que api/static sombrea los iconos de django.contrib.admin."""

from django.contrib.staticfiles.finders import find


def test_api_icons_shadow_django_admin():
    """Los iconos Carbon en api/static deben resolverse antes que los de Django."""
    path = find("admin/img/icon-addlink.svg")
    assert path is not None, "icon-addlink.svg no encontrado"
    # Después de crear los SVGs en api/static, este assert debe pasar:
    assert "api" in path, (
        f"icon-addlink.svg se resolvió desde {path!r}, "
        "esperaba que viniera de api/static (revisa el orden de INSTALLED_APPS)"
    )
