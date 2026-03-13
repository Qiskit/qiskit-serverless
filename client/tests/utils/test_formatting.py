# This code is a Qiskit project.
#
# (C) Copyright IBM 2025.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""Tests for formatting utilities."""

import pytest

from qiskit_serverless.utils.formatting import format_provider_name_and_title


class TestFormatProviderNameAndTitle:
    """Tests for format_provider_name_and_title function."""

    @pytest.mark.parametrize(
        "request_provider,title,expected_provider,expected_title",
        [
            # When provider is explicitly provided, it always takes precedence
            pytest.param("my-provider", "my-function", "my-provider", "my-function", id="simple_provider_and_title"),
            pytest.param(
                "provider1",
                "provider2/function",
                "provider1",
                "provider2/function",
                id="provider_overrides_title_slash",
            ),
        ],
    )
    def test_provider_takes_precedence(self, request_provider, title, expected_provider, expected_title):
        """Test that when provider is given, it takes precedence over title parsing."""
        provider, result_title = format_provider_name_and_title(request_provider, title)
        assert provider == expected_provider
        assert result_title == expected_title

    @pytest.mark.parametrize(
        "request_provider,title,expected_provider,expected_title",
        [
            # When provider is None or empty (falsy), parse from title
            pytest.param(None, "my-function", None, "my-function", id="none_provider_simple_title"),
            pytest.param("", "my-function", None, "my-function", id="empty_provider_simple_title"),
        ],
    )
    def test_falsy_provider_with_simple_title(self, request_provider, title, expected_provider, expected_title):
        """Test that None or empty provider with simple title returns None provider."""
        provider, result_title = format_provider_name_and_title(request_provider, title)
        assert provider == expected_provider
        assert result_title == expected_title

    @pytest.mark.parametrize(
        "request_provider,title,expected_provider,expected_title",
        [
            # When provider is None or empty, parse provider from title if it contains slash
            pytest.param(None, "my-provider/my-function", "my-provider", "my-function", id="none_provider_with_slash"),
            pytest.param("", "my-provider/my-function", "my-provider", "my-function", id="empty_provider_with_slash"),
        ],
    )
    def test_falsy_provider_parses_from_title(self, request_provider, title, expected_provider, expected_title):
        """Test that None or empty provider parses provider from title when slash present."""
        provider, result_title = format_provider_name_and_title(request_provider, title)
        assert provider == expected_provider
        assert result_title == expected_title

    def test_title_without_slash(self):
        """Test title without slash returns original values."""
        provider, title = format_provider_name_and_title("provider", "function")
        assert provider == "provider"
        assert title == "function"

    @pytest.mark.parametrize(
        "request_provider,title,expected_provider,expected_title",
        [
            pytest.param(
                "my-provider_123", "my-function.v2", "my-provider_123", "my-function.v2", id="special_characters"
            ),
            pytest.param("my provider", "my function", "my provider", "my function", id="spaces"),
            pytest.param("MyProvider", "MyFunction", "MyProvider", "MyFunction", id="case_sensitivity"),
            pytest.param("provider", "función", "provider", "función", id="unicode"),
        ],
    )
    def test_special_characters_and_encoding(self, request_provider, title, expected_provider, expected_title):
        """Test handling of special characters, spaces, case, and unicode."""
        provider, result_title = format_provider_name_and_title(request_provider, title)
        assert provider == expected_provider
        assert result_title == expected_title
