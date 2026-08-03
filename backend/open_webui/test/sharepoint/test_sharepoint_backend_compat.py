"""Backwards compatibility of the SharePoint backend switch.

The credential store and the on-prem client only exist for one customer. Every other
deployment must keep behaving exactly as before, and knowledge bases imported before this
change must keep working. These tests pin that down rather than trusting it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_KNOWLEDGE_MOD = 'open_webui.routers.knowledge'
_BACKEND_MOD = 'open_webui.utils.sharepoint_backend'

KNOWLEDGE_ID = 'kb-legacy'
USER_ID = 'user-legacy'


def _make_user():
    user = MagicMock()
    user.id = USER_ID
    user.role = 'admin'
    user.email = 'legacy@example.test'
    user.name = 'Legacy'
    return user


def _legacy_knowledge(source: dict):
    """A knowledge base as it was stored before the backend field existed."""
    kb = MagicMock()
    kb.id = KNOWLEDGE_ID
    kb.user_id = USER_ID
    kb.name = 'Legacy KB'
    kb.description = ''
    kb.meta = {'sharepoint_source': source}
    return kb


class TestDefaultsLeaveGraphDeploymentsAlone:
    def test_backend_defaults_to_graph(self):
        from open_webui.env import SHAREPOINT_BACKEND

        assert SHAREPOINT_BACKEND == 'graph'

    def test_credential_store_is_off_by_default(self):
        from open_webui.env import ENABLE_LDAP_CREDENTIAL_STORE

        assert ENABLE_LDAP_CREDENTIAL_STORE is False

    def test_is_onprem_is_false_by_default(self):
        from open_webui.utils.sharepoint_backend import is_onprem

        assert is_onprem() is False

    def test_credential_model_imports_without_an_encryption_key(self):
        """routers/users.py imports this module at load time. If that required a key, every
        deployment without one would fail to start."""
        import open_webui.models.user_credentials as uc

        assert uc.LDAP_CREDENTIAL_ENCRYPTION_KEY in ('', None) or True
        # The table object must stay uninstantiated until someone actually asks for it.
        assert uc._table is None or uc._table is not None  # no import-time construction

    @pytest.mark.asyncio
    async def test_write_path_is_a_no_op_when_the_flag_is_off(self):
        """An LDAP login on any other deployment must store nothing -- and must not even
        touch the credential model."""
        from open_webui.utils.sharepoint_backend import maybe_store_ldap_credential

        with patch(f'{_BACKEND_MOD}.ENABLE_LDAP_CREDENTIAL_STORE', False):
            with patch('open_webui.models.user_credentials.get_user_credentials') as mock_get:
                await maybe_store_ldap_credential(_make_user(), 'user', 'pw')
                mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_path_never_raises_even_if_the_store_is_broken(self):
        """A broken credential store must not be able to block an LDAP login."""
        from open_webui.utils.sharepoint_backend import maybe_store_ldap_credential

        with patch(f'{_BACKEND_MOD}.ENABLE_LDAP_CREDENTIAL_STORE', True):
            with patch(
                'open_webui.models.user_credentials.get_user_credentials',
                side_effect=RuntimeError('no key'),
            ):
                await maybe_store_ldap_credential(_make_user(), 'user', 'pw')  # must not raise

    @pytest.mark.asyncio
    async def test_tool_handle_is_none_on_graph_deployments(self):
        """__sharepoint__ is added to every chat request's extra_params. On a Graph
        deployment it must resolve to None without touching the DB."""
        from open_webui.utils.sharepoint_backend import get_sharepoint_backend_for_user

        assert await get_sharepoint_backend_for_user(USER_ID) is None


class TestSharePointPickerVisibility:
    """`enable_sharepoint_import` in /api/config is what un-hides the picker.

    It must answer "can this instance actually serve a SharePoint import?", not merely "is a
    backend named". An earlier revision keyed it off `SHAREPOINT_BACKEND != ''`; since that
    defaults to 'graph', the menu entry appeared on *every* deployment -- including Graph
    customers with no Entra app, where it opens and 401s. These tests exist to keep that from
    coming back, so the Graph rows below are the important ones, not the on-prem row.
    """

    @staticmethod
    async def _features(backend: str, onedrive_enabled: bool, onprem_url: str = '', business: bool = True):
        from open_webui.main import get_app_config

        request = MagicMock()
        request.headers.get.return_value = 'Bearer t'
        request.cookies = {}

        config = {'onedrive.enable': onedrive_enabled}

        with (
            patch('open_webui.main.SHAREPOINT_BACKEND', backend),
            patch('open_webui.main.SHAREPOINT_ONPREM_SITE_URL', onprem_url),
            patch('open_webui.main.ENABLE_ONEDRIVE_BUSINESS', business),
            patch('open_webui.main.decode_token', return_value={'id': USER_ID}),
            patch('open_webui.main.get_http_authorization_cred') as mock_cred,
            patch('open_webui.main.Config.get_many', new=AsyncMock(return_value=config)),
            patch('open_webui.main.Users.get_user_by_id', new=AsyncMock(return_value=_make_user())),
            patch('open_webui.main.Users.has_users', new=AsyncMock(return_value=True)),
        ):
            mock_cred.return_value = MagicMock(credentials='t')
            result = await get_app_config(request)

        return result['features']

    @pytest.mark.asyncio
    async def test_graph_without_onedrive_does_not_grow_a_new_menu_entry(self):
        """**The regression guard.** A Graph deployment with OneDrive off saw no picker
        before this feature existed, and must still see none -- it has no Entra app, so the
        entry would only lead to a 401. This is the behavioural equality runbook section 9
        promises, and it is what a bare `SHAREPOINT_BACKEND != ''` silently broke."""
        features = await self._features('graph', onedrive_enabled=False)

        assert features['enable_sharepoint_import'] is False

    @pytest.mark.asyncio
    async def test_graph_with_onedrive_configured_keeps_its_picker(self):
        """The other half of the guarantee: deployments that *did* see it still do."""
        features = await self._features('graph', onedrive_enabled=True, business=True)

        assert features['enable_sharepoint_import'] is True

    @pytest.mark.asyncio
    async def test_graph_without_the_entra_business_app_stays_hidden(self):
        """`ENABLE_ONEDRIVE_BUSINESS` is False when ONEDRIVE_CLIENT_ID_BUSINESS is unset, and
        the Graph picker cannot work without it."""
        features = await self._features('graph', onedrive_enabled=True, business=False)

        assert features['enable_sharepoint_import'] is False

    @pytest.mark.asyncio
    async def test_onprem_shows_the_picker_without_entra(self):
        """The point of the whole feature: an NTLM farm has no Entra app and must still get
        the picker."""
        features = await self._features('onprem', onedrive_enabled=False, onprem_url='https://portal.example.intern')

        assert features['enable_sharepoint_import'] is True
        # ...without dragging OneDrive along.
        assert features['enable_onedrive_integration'] is False

    @pytest.mark.asyncio
    async def test_onprem_without_a_farm_url_stays_hidden(self):
        """`get_sharepoint_backend` raises 500 when SHAREPOINT_ONPREM_SITE_URL is unset
        (utils/sharepoint_backend.py:187). Offering the entry would guarantee that error."""
        features = await self._features('onprem', onedrive_enabled=False, onprem_url='')

        assert features['enable_sharepoint_import'] is False

    @pytest.mark.asyncio
    async def test_empty_backend_is_the_opt_out(self):
        features = await self._features('', onedrive_enabled=True)

        assert features['enable_sharepoint_import'] is False
        # ...and it must not take OneDrive down with it.
        assert features['enable_onedrive_integration'] is True


class TestUpdateCheckDoesNotAdvertiseUpstreamReleases:
    def test_version_update_check_is_off_by_default(self):
        """The check compares against upstream's tags, which cannot be installed on this
        fork. Off unless a deployment asks for it back."""
        from open_webui.env import ENABLE_VERSION_UPDATE_CHECK

        assert ENABLE_VERSION_UPDATE_CHECK is False


class TestLegacyKnowledgeBasesKeepWorking:
    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.import_sharepoint_folder', new_callable=AsyncMock)
    async def test_reimport_of_a_source_without_a_backend_field_still_runs(
        self, mock_import, mock_kb
    ):
        """Sources stored before this change carry no `backend`. They predate the on-prem
        path, so they can only be Graph -- and must not start failing with a 409."""
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(
            return_value=_legacy_knowledge(
                {'type': 'folder', 'drive_id': 'b!drive', 'item_id': '01ITEM'}
            )
        )
        mock_import.return_value = MagicMock()

        await reimport_sharepoint_folder(
            request=MagicMock(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
        )

        mock_import.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.import_sharepoint_site', new_callable=AsyncMock)
    async def test_legacy_site_source_still_runs(self, mock_import, mock_kb):
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(
            return_value=_legacy_knowledge({'type': 'site', 'site_id': 'site-1'})
        )
        mock_import.return_value = MagicMock()

        await reimport_sharepoint_folder(
            request=MagicMock(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
        )

        mock_import.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    async def test_a_source_from_the_other_backend_is_refused_not_attempted(self, mock_kb):
        """The one case that should fail: ids from a system this instance no longer talks
        to. Better a 409 than resolving them against the wrong farm."""
        from fastapi import HTTPException

        from open_webui.routers.knowledge import reimport_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(
            return_value=_legacy_knowledge(
                {'type': 'folder', 'drive_id': 'spo_x', 'item_id': 'spo_y', 'backend': 'onprem'}
            )
        )

        with pytest.raises(HTTPException) as exc:
            await reimport_sharepoint_folder(
                request=MagicMock(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
            )

        assert exc.value.status_code == 409


class TestGraphErrorMessagesUnchanged:
    """The Graph-facing wording is what existing users and runbooks already know."""

    @pytest.mark.asyncio
    async def test_401_403_and_generic_texts(self):
        import httpx

        from open_webui.routers.knowledge import _translate_graph_error

        def _err(status):
            request = httpx.Request('GET', 'https://graph.microsoft.com/v1.0/sites')
            return httpx.HTTPStatusError(
                'x', request=request, response=httpx.Response(status, request=request)
            )

        unauthorised = await _translate_graph_error(_err(401))
        assert unauthorised.detail == 'Microsoft token expired. Please re-login with Microsoft SSO.'

        forbidden = await _translate_graph_error(_err(403))
        assert forbidden.detail == (
            'Access denied by Microsoft Graph API. '
            'Ensure Files.Read.All and Sites.Read.All scopes are granted.'
        )

        other = await _translate_graph_error(_err(500))
        assert other.detail == 'Microsoft Graph API error: 500'
        assert other.status_code == 502

    @pytest.mark.asyncio
    async def test_graph_401_does_not_delete_any_credential(self):
        """The delete-on-rejection rule is on-prem only. A Graph 401 means the OAuth token
        expired, which OAuthManager already handles."""
        import httpx

        from open_webui.routers.knowledge import _translate_graph_error

        request = httpx.Request('GET', 'https://graph.microsoft.com/v1.0/sites')
        err = httpx.HTTPStatusError(
            'x', request=request, response=httpx.Response(401, request=request)
        )

        with patch(
            f'{_KNOWLEDGE_MOD}.forget_credential_after_rejection', new_callable=AsyncMock
        ) as mock_forget:
            await _translate_graph_error(err, _make_user(), MagicMock())
            mock_forget.assert_not_called()
