"""The SharePoint KB import driven by the on-prem backend.

The existing import tests exercise the Graph path. This file covers the same endpoints
with SHAREPOINT_BACKEND=onprem, which is a genuinely different route: the on-prem client
issues opaque `spo_` ids, hands out no pre-signed download URL (so the importer must fall
through to download_file_by_id), and its 401 means the stored credential is dropped.

The farm itself is replaced by an httpx.MockTransport, so this runs without a VPN. The
real farm responses are verified separately in test_sharepoint_onprem_client.py and by the
live runs recorded in docs/LDAP_SHAREPOINT_BACKEND.md.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from open_webui.utils.sharepoint_onprem_client import SharePointOnPremClient, encode_id

_KNOWLEDGE_MOD = 'open_webui.routers.knowledge'

KNOWLEDGE_ID = 'kb-onprem'
USER_ID = 'user-onprem'
LIB_PATH = '/Dokumente zur Befragung'
LIB = encode_id(LIB_PATH)

PDF = b'%PDF-1.7 fake content'


def _make_user():
    user = MagicMock()
    user.id = USER_ID
    user.email = 'onprem@example.test'
    user.name = 'On Prem'
    user.role = 'admin'
    return user


def _make_knowledge():
    kb = MagicMock()
    kb.id = KNOWLEDGE_ID
    kb.user_id = USER_ID
    kb.name = 'On-prem KB'
    kb.description = ''
    kb.meta = {}
    return kb


def _farm(request: httpx.Request) -> httpx.Response:
    """Minimal stand-in for the farm: one library, two files, no subfolders."""
    url = str(request.url)
    if '/$value' in url:
        return httpx.Response(200, content=PDF)
    if 'GetFileByServerRelativeUrl' in url:
        return httpx.Response(
            200,
            json={
                'Name': 'FAQ.pdf',
                'Length': str(len(PDF)),
                'ServerRelativeUrl': f'{LIB_PATH}/FAQ.pdf',
            },
        )
    if 'GetFolderByServerRelativeUrl' in url:
        return httpx.Response(
            200,
            json={
                'Name': 'Dokumente zur Befragung',
                'ServerRelativeUrl': LIB_PATH,
                'Folders': [],
                'Files': [
                    {
                        'Name': 'FAQ.pdf',
                        'Length': str(len(PDF)),
                        'ServerRelativeUrl': f'{LIB_PATH}/FAQ.pdf',
                    },
                    {
                        'Name': 'Einladung.pdf',
                        'Length': str(len(PDF)),
                        'ServerRelativeUrl': f'{LIB_PATH}/Einladung.pdf',
                    },
                ],
            },
        )
    return httpx.Response(404, json={})


def _onprem_client() -> SharePointOnPremClient:
    return SharePointOnPremClient(
        account='skkiel\\user',
        password='pw',
        base_url='https://portal.example.intern',
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(_farm), headers={'Accept': 'application/json'}
        ),
    )


@pytest.fixture
def onprem(monkeypatch):
    """Force the resolver to hand out the on-prem client, as SHAREPOINT_BACKEND=onprem does."""
    client = _onprem_client()

    async def _resolve(request, user, db):
        return client

    monkeypatch.setattr(f'{_KNOWLEDGE_MOD}.get_sharepoint_backend', _resolve)
    monkeypatch.setattr(f'{_KNOWLEDGE_MOD}.is_onprem', lambda: True)
    monkeypatch.setattr(f'{_KNOWLEDGE_MOD}.SHAREPOINT_BACKEND', 'onprem')
    return client


class TestOnPremImport:
    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.upload_file_handler', new_callable=AsyncMock)
    @patch(f'{_KNOWLEDGE_MOD}.process_file', new_callable=AsyncMock)
    async def test_folder_import_downloads_every_file(
        self, mock_process, mock_upload, mock_kb, onprem
    ):
        """The whole point: files from an NTLM-only farm end up in a knowledge base."""
        from open_webui.routers.knowledge import SharePointImportForm, import_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_upload.return_value = {'status': True, 'id': 'file-1'}

        result = await import_sharepoint_folder(
            request=MagicMock(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=LIB, item_id=LIB),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.total_files == 2
        assert result.imported == 2
        assert result.failed == 0
        assert mock_upload.call_count == 2

        # On-prem items carry no pre-signed URL, so the importer must have taken the
        # /$value fallback -- the only path that carries NTLM.
        uploaded = [c.kwargs['file'].filename for c in mock_upload.call_args_list]
        assert sorted(uploaded) == ['Einladung.pdf', 'FAQ.pdf']

    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.upload_file_handler', new_callable=AsyncMock)
    @patch(f'{_KNOWLEDGE_MOD}.process_file', new_callable=AsyncMock)
    async def test_single_file_import_reresolves_metadata(
        self, mock_process, mock_upload, mock_kb, onprem
    ):
        from open_webui.routers.knowledge import SharePointImportFileForm, import_sharepoint_file

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_upload.return_value = {'status': True, 'id': 'file-1'}

        result = await import_sharepoint_file(
            request=MagicMock(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportFileForm(
                drive_id=LIB, item_id=encode_id(f'{LIB_PATH}/FAQ.pdf'), path=''
            ),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.knowledge_id == KNOWLEDGE_ID
        assert result.filename == 'FAQ.pdf'
        assert result.file_id == 'file-1'
        assert mock_upload.call_count == 1

    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    async def test_list_folder_returns_display_names(self, mock_kb, onprem):
        from open_webui.routers.knowledge import SharePointImportForm, list_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        result = await list_sharepoint_folder(
            request=MagicMock(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=LIB, item_id=LIB),
            user=_make_user(),
            db=MagicMock(),
        )

        assert [f.name for f in result.files] == ['FAQ.pdf', 'Einladung.pdf']
        # Ids must stay opaque -- they travel back as path parameters.
        assert all('/' not in f.item_id for f in result.files)


class TestOnPremSourceMetadata:
    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.upload_file_handler', new_callable=AsyncMock)
    @patch(f'{_KNOWLEDGE_MOD}.process_file', new_callable=AsyncMock)
    async def test_import_records_the_backend_that_issued_the_ids(
        self, mock_process, mock_upload, mock_kb, onprem
    ):
        """Graph ids and on-prem ids are indistinguishable by inspection, so the source
        has to say which system issued them."""
        from open_webui.routers.knowledge import SharePointImportForm, import_sharepoint_folder

        knowledge = _make_knowledge()
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=knowledge)
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_upload.return_value = {'status': True, 'id': 'file-1'}

        await import_sharepoint_folder(
            request=MagicMock(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=LIB, item_id=LIB),
            user=_make_user(),
            db=MagicMock(),
        )

        form = mock_kb.update_knowledge_by_id.call_args.kwargs['form_data']
        assert form.meta['sharepoint_source']['backend'] == 'onprem'

    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    async def test_reimport_of_a_graph_source_is_refused(self, mock_kb, onprem):
        """A KB imported from Graph must not have its ids resolved against the farm."""
        from fastapi import HTTPException

        from open_webui.routers.knowledge import reimport_sharepoint_folder

        knowledge = _make_knowledge()
        knowledge.meta = {
            'sharepoint_source': {
                'type': 'folder',
                'drive_id': 'b!graph-drive',
                'item_id': '01GRAPHITEM',
                'backend': 'graph',
            }
        }
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=knowledge)

        with pytest.raises(HTTPException) as exc:
            await reimport_sharepoint_folder(
                request=MagicMock(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
            )

        assert exc.value.status_code == 409
        assert 'graph' in exc.value.detail


class TestOnPremRejection:
    @pytest.mark.asyncio
    @patch(f'{_KNOWLEDGE_MOD}.Knowledges')
    @patch(f'{_KNOWLEDGE_MOD}.forget_credential_after_rejection', new_callable=AsyncMock)
    async def test_a_real_401_drops_the_stored_credential(
        self, mock_forget, mock_kb, monkeypatch
    ):
        """The entire no-retry policy: a rejected password is deleted, never retried."""
        from fastapi import HTTPException

        from open_webui.routers.knowledge import SharePointImportForm, list_sharepoint_folder

        def always_401(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        client = SharePointOnPremClient(
            account='skkiel\\user',
            password='pw',
            base_url='https://portal.example.intern',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(always_401)),
        )

        async def _resolve(request, user, db):
            return client

        monkeypatch.setattr(f'{_KNOWLEDGE_MOD}.get_sharepoint_backend', _resolve)
        monkeypatch.setattr(f'{_KNOWLEDGE_MOD}.is_onprem', lambda: True)
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        with pytest.raises(HTTPException) as exc:
            await list_sharepoint_folder(
                request=MagicMock(),
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=LIB, item_id=LIB),
                user=_make_user(),
                db=MagicMock(),
            )

        assert exc.value.status_code == 401
        assert 'nicht wiederholt' in exc.value.detail
        mock_forget.assert_awaited_once()
