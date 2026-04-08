"""Tests for Config model."""

import pytest
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache

from core.config_key import ConfigKey
from core.models import Config


class TestConfig:
    """Tests for Config model."""

    @pytest.fixture(autouse=True)
    def _setup(self, db, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        cache.clear()
        yield
        cache.clear()

    def test_unique_name_constraint(self):
        """Test that name field is unique."""
        Config.objects.create(name="key", value="1")
        with pytest.raises(Exception):
            Config.objects.create(name="key", value="2")

    def test_add_defaults_creates_configs(self):
        """Test that add_defaults creates all configs from ConfigKey enum."""
        Config.add_defaults()

        for config_key in ConfigKey:
            config = Config.objects.get(name=config_key.value)
            assert config.value == settings.DYNAMIC_CONFIG_DEFAULTS[config_key.value]["default"]

    def test_get_uses_cache(self):
        """Test that get method reads from the db the first time, then it uses the cache."""
        # first access the value is obtained from the database (assert the objects.get)
        with patch.object(Config.objects, "get") as mock_get:
            mock_get.return_value.value = "false"
            result = Config.get(ConfigKey.MAINTENANCE)
            mock_get.assert_called()
            assert result == "false"

        with patch.object(Config.objects, "get") as mock_get:
            # second access the value is obtained from the cache (assert the objects.get is not called)
            result = Config.get(ConfigKey.MAINTENANCE)
            mock_get.assert_not_called()
            assert result == "false"

    def test_set_updates_db_and_cache(self):
        """Test that set() updates both DB and cache."""
        Config.add_defaults()

        # cache the default value
        result = Config.get(ConfigKey.MAINTENANCE)
        assert result == "false"

        # use set() to change value
        Config.set(ConfigKey.MAINTENANCE, "true")

        # get() returns the new value (from cache)
        value = Config.get(ConfigKey.MAINTENANCE)
        assert value == "true"

        # verify DB was also updated
        config = Config.objects.get(name=ConfigKey.MAINTENANCE.value)
        assert config.value == "true"
