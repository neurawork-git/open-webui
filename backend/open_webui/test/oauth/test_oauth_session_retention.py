"""Regression tests: OAuth session must NOT be deleted on transient refresh failures.

Covers OAuthClientManager.get_oauth_token (utils/oauth.py:767) and
OAuthManager.get_oauth_token (utils/oauth.py:1025).  Both have the same
invariant: a failed token refresh keeps the session row alive so the user
does not have to re-link on every transient IdP/network error.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_expired_session(session_id="sess-1", provider="microsoft", user_id="u-1"):
    session = MagicMock()
    session.id = session_id
    session.provider = provider
    session.user_id = user_id
    session.token = {"access_token": "old-token"}
    # Expired 10 minutes ago
    session.expires_at = (datetime.now() - timedelta(minutes=10)).timestamp()
    return session


# ---------------------------------------------------------------------------
# OAuthClientManager
# ---------------------------------------------------------------------------

class TestOAuthClientManagerSessionRetention:
    """OAuthClientManager.get_oauth_token must not delete session on refresh failure."""

    @pytest.mark.asyncio
    async def test_refresh_fail_does_not_delete_session(self):
        from open_webui.utils.oauth import OAuthClientManager

        manager = OAuthClientManager.__new__(OAuthClientManager)
        manager.oauth = MagicMock()
        manager.app = MagicMock()
        manager.clients = {}

        expired_session = _make_expired_session()

        with patch(
            "open_webui.utils.oauth.OAuthSessions.get_session_by_provider_and_user_id",
            new_callable=AsyncMock,
            return_value=expired_session,
        ), patch(
            "open_webui.utils.oauth.OAuthSessions.delete_session_by_id",
            new_callable=AsyncMock,
        ) as mock_delete, patch.object(
            manager, "_refresh_token", new_callable=AsyncMock, return_value=None
        ):
            result = await manager.get_oauth_token("u-1", "microsoft")

        assert result is None
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_fail_returns_none(self):
        from open_webui.utils.oauth import OAuthClientManager

        manager = OAuthClientManager.__new__(OAuthClientManager)
        manager.oauth = MagicMock()
        manager.app = MagicMock()
        manager.clients = {}

        expired_session = _make_expired_session()

        with patch(
            "open_webui.utils.oauth.OAuthSessions.get_session_by_provider_and_user_id",
            new_callable=AsyncMock,
            return_value=expired_session,
        ), patch(
            "open_webui.utils.oauth.OAuthSessions.delete_session_by_id",
            new_callable=AsyncMock,
        ), patch.object(
            manager, "_refresh_token", new_callable=AsyncMock, return_value=None
        ):
            result = await manager.get_oauth_token("u-1", "microsoft")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_session_returns_none_without_delete(self):
        from open_webui.utils.oauth import OAuthClientManager

        manager = OAuthClientManager.__new__(OAuthClientManager)
        manager.oauth = MagicMock()
        manager.app = MagicMock()
        manager.clients = {}

        with patch(
            "open_webui.utils.oauth.OAuthSessions.get_session_by_provider_and_user_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "open_webui.utils.oauth.OAuthSessions.delete_session_by_id",
            new_callable=AsyncMock,
        ) as mock_delete:
            result = await manager.get_oauth_token("u-1", "microsoft")

        assert result is None
        mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# OAuthManager
# ---------------------------------------------------------------------------

class TestOAuthManagerSessionRetention:
    """OAuthManager.get_oauth_token must not delete session on refresh failure."""

    @pytest.mark.asyncio
    async def test_refresh_fail_does_not_delete_session(self):
        from open_webui.utils.oauth import OAuthManager

        with patch("open_webui.utils.oauth.OAUTH_PROVIDERS", {}):
            manager = OAuthManager.__new__(OAuthManager)
            manager.oauth = MagicMock()
            manager.app = MagicMock()
            manager._clients = {}

        expired_session = _make_expired_session()

        with patch(
            "open_webui.utils.oauth.OAuthSessions.get_session_by_id_and_user_id",
            new_callable=AsyncMock,
            return_value=expired_session,
        ), patch(
            "open_webui.utils.oauth.OAuthSessions.delete_session_by_id",
            new_callable=AsyncMock,
        ) as mock_delete, patch.object(
            manager, "_refresh_token", new_callable=AsyncMock, return_value=None
        ):
            result = await manager.get_oauth_token("u-1", "sess-1")

        assert result is None
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_session_returns_none_without_delete(self):
        from open_webui.utils.oauth import OAuthManager

        with patch("open_webui.utils.oauth.OAUTH_PROVIDERS", {}):
            manager = OAuthManager.__new__(OAuthManager)
            manager.oauth = MagicMock()
            manager.app = MagicMock()
            manager._clients = {}

        with patch(
            "open_webui.utils.oauth.OAuthSessions.get_session_by_id_and_user_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "open_webui.utils.oauth.OAuthSessions.delete_session_by_id",
            new_callable=AsyncMock,
        ) as mock_delete:
            result = await manager.get_oauth_token("u-1", "sess-1")

        assert result is None
        mock_delete.assert_not_called()
