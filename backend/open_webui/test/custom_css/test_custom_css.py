"""Tests for the fork-local live custom CSS feature.

The interesting failure mode here is not a wrong response body — it is the route
silently losing to the `/static` mount after an upstream merge, which would make
branding revert to the (empty) file without any error anywhere.
"""

import re
from pathlib import Path

import pytest

from open_webui.routers import custom_css

MAIN_PY = Path(__file__).resolve().parents[2] / 'main.py'


class TestRouteRegistrationOrder:
    """main.py source-level guards. Cheap, and they catch the two ways this breaks."""

    @pytest.fixture(scope='class')
    def main_source(self):
        return MAIN_PY.read_text(encoding='utf-8')

    def test_router_is_registered(self, main_source):
        assert re.search(r'^app\.include_router\(\s*custom_css\.router', main_source, re.M), (
            'custom_css.router is not registered in main.py — /static/custom.css falls '
            'back to the empty file in STATIC_DIR and all custom branding disappears.'
        )

    def test_router_registered_before_static_mount(self, main_source):
        # Anchored at line start: the FORK comment above the registration mentions
        # the mount by name, and an unanchored search would match that instead.
        router_match = re.search(r'^app\.include_router\(\s*custom_css\.router', main_source, re.M)
        mount_match = re.search(r"^app\.mount\('/static'", main_source, re.M)

        assert router_match is not None
        assert mount_match is not None, "app.mount('/static', ...) not found in main.py"

        assert router_match.start() < mount_match.start(), (
            'app.include_router(custom_css.router) must come before '
            "app.mount('/static', ...) — FastAPI matches routes in registration order, "
            'so a later router is shadowed by the static mount and never called.'
        )


class TestConfigKey:
    def test_key_has_a_default(self):
        from open_webui.config import DEFAULT_CONFIG

        assert custom_css.CONFIG_KEY in DEFAULT_CONFIG, (
            f'{custom_css.CONFIG_KEY} missing from DEFAULT_CONFIG — Config.get would '
            'return None instead of an empty stylesheet.'
        )
        assert DEFAULT_CONFIG[custom_css.CONFIG_KEY] == ''


class TestStoredCss:
    @pytest.mark.asyncio
    async def test_non_string_value_is_ignored(self, monkeypatch):
        """The config column is JSON; a dict written via the generic config import
        endpoint must not end up being served as a stylesheet."""

        async def fake_get(key, default=None):
            return {'not': 'css'}

        monkeypatch.setattr(custom_css.Config, 'get', fake_get)
        assert await custom_css._stored_css() == ''

    @pytest.mark.asyncio
    async def test_string_value_is_returned(self, monkeypatch):
        async def fake_get(key, default=None):
            return 'body { color: red; }'

        monkeypatch.setattr(custom_css.Config, 'get', fake_get)
        assert await custom_css._stored_css() == 'body { color: red; }'


class TestSizeLimit:
    @pytest.mark.asyncio
    async def test_oversized_css_is_rejected(self, monkeypatch):
        from fastapi import HTTPException

        upserted = []

        async def fake_upsert(updates):
            upserted.append(updates)

        monkeypatch.setattr(custom_css.Config, 'upsert', fake_upsert)

        form = custom_css.CustomCssForm(css='a' * (custom_css.MAX_CSS_BYTES + 1))

        with pytest.raises(HTTPException) as exc_info:
            await custom_css.set_custom_css(form, user=None)

        assert exc_info.value.status_code == 400
        assert not upserted, 'oversized CSS must not reach the config table'

    @pytest.mark.asyncio
    async def test_multibyte_css_is_measured_in_bytes(self, monkeypatch):
        """A CSS string under the limit in characters can still exceed it in UTF-8
        bytes — content:'ü' and friends are 2 bytes each."""
        from fastapi import HTTPException

        monkeypatch.setattr(custom_css.Config, 'upsert', lambda updates: None)

        # Half the limit in characters, but every character is 2 bytes.
        form = custom_css.CustomCssForm(css='ü' * (custom_css.MAX_CSS_BYTES // 2 + 1))

        with pytest.raises(HTTPException):
            await custom_css.set_custom_css(form, user=None)
