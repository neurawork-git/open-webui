"""Tests for the SharePoint import endpoint in knowledge.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from open_webui.utils.graph_client import GraphFolderListing, GraphFileItem
from open_webui.utils.oauth import OAuthManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KNOWLEDGE_ID = "kb-123"
USER_ID = "user-1"
DRIVE_ID = "drive-abc"
ITEM_ID = "item-xyz"


def _make_user(user_id=USER_ID, role="user"):
    user = MagicMock()
    user.id = user_id
    user.email = "test@example.com"
    user.name = "Test User"
    user.role = role
    return user


def _make_knowledge(knowledge_id=KNOWLEDGE_ID, user_id=USER_ID):
    kb = MagicMock()
    kb.id = knowledge_id
    kb.user_id = user_id
    kb.name = "Test KB"
    kb.description = "Test knowledge base"
    kb.meta = {}
    kb.model_dump = MagicMock(return_value={"id": knowledge_id, "user_id": user_id})
    return kb


def _make_oauth_session(access_token="graph-token-123"):
    session = MagicMock()
    session.token = {"access_token": access_token}
    return session


def _make_folder_listing(
    files=None, skipped_folders=None, folder_name="TestFolder"
):
    if files is None:
        files = [
            GraphFileItem(
                id="f1", name="doc1.pdf", size=1024,
                content_type="application/pdf",
                download_url="https://cdn.example.com/doc1.pdf",
            ),
            GraphFileItem(
                id="f2", name="report.docx", size=2048,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                download_url="https://cdn.example.com/report.docx",
            ),
        ]
    return GraphFolderListing(
        folder_name=folder_name,
        folder_path="/drives/drive-abc/root:/Documents",
        drive_id=DRIVE_ID,
        item_id=ITEM_ID,
        files=files,
        skipped_folders=skipped_folders or [],
    )


# Module paths for patching
_KNOWLEDGE_MOD = "open_webui.routers.knowledge"
# The Microsoft credential path moved out of the router into the backend resolver,
# so GraphClient and OAuthSessions are patched there now. Behaviour is unchanged.
_BACKEND_MOD = "open_webui.utils.sharepoint_backend"

# The router reads the SharePoint size cap via `Config.get(...)` (the
# per-key Config system), not via a request.app.state.config attribute.
# `_make_request` stashes the desired limit here; the autouse fixture below
# feeds it back out of a mocked Config.get.
_SHAREPOINT_SIZE_LIMIT_MB = {"value": 0}


@pytest.fixture(autouse=True)
def _patch_sharepoint_config_get():
    async def _fake_get(key, default=None):
        if key == "rag.sharepoint.import_max_total_size_mb":
            return _SHAREPOINT_SIZE_LIMIT_MB["value"]
        return default

    with patch(f"{_KNOWLEDGE_MOD}.Config") as mock_config:
        mock_config.get = AsyncMock(side_effect=_fake_get)
        yield mock_config
    _SHAREPOINT_SIZE_LIMIT_MB["value"] = 0


def _make_request(
    sharepoint_import_max_total_size_mb: int = 0,
    access_token: str = "graph-token-123",
    session_cookie: str = "test-session-id",
) -> MagicMock:
    """Build a Request mock whose app.state carries an oauth_manager.get_oauth_token
    that returns a valid Microsoft token, and register the SharePoint size cap
    with the mocked Config.get (see `_patch_sharepoint_config_get`). Pass
    access_token=None to simulate refresh failure and session_cookie=None to
    simulate a missing oauth_session_id cookie."""
    _SHAREPOINT_SIZE_LIMIT_MB["value"] = sharepoint_import_max_total_size_mb
    request = MagicMock()
    request.cookies = {"oauth_session_id": session_cookie} if session_cookie else {}
    token_payload = {"access_token": access_token} if access_token else None
    request.app.state.oauth_manager = MagicMock(spec=OAuthManager)
    request.app.state.oauth_manager.get_oauth_token = AsyncMock(
        return_value=token_payload
    )
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSharePointImport:
    """Tests for POST /knowledge/{id}/sharepoint/import"""

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_successful_import(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """Import 2 files → both succeed."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing()
        graph_instance.download_file.return_value = b"file content"
        mock_graph_cls.return_value = graph_instance

        mock_upload.side_effect = None; mock_upload.return_value = {"status": True, "id": "file-id-1"}

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        assert result.knowledge_id == KNOWLEDGE_ID
        assert result.folder_name == "TestFolder"
        assert result.total_files == 2
        assert result.imported == 2
        assert result.failed == 0
        assert result.errors == []
        assert graph_instance.download_file.call_count == 2
        assert mock_upload.call_count == 2

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_partial_failure(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """1 file succeeds, 1 fails → partial result reported."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing()
        # First download succeeds, second fails
        graph_instance.download_file.side_effect = [
            b"file content",
            httpx.HTTPStatusError("download failed", request=MagicMock(), response=MagicMock()),
        ]
        mock_graph_cls.return_value = graph_instance

        mock_upload.side_effect = None; mock_upload.return_value = {"status": True, "id": "file-id-1"}

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        assert result.imported == 1
        assert result.failed == 1
        assert len(result.errors) == 1
        assert result.errors[0].filename == "report.docx"

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_missing_download_url_falls_back_to_content_endpoint(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """File without download_url but with drive_id → /content fallback used."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        files = [
            GraphFileItem(
                id="f1", name="restricted.pdf", size=4096,
                content_type="application/pdf",
                download_url=None,
                drive_id=DRIVE_ID,
            ),
        ]
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=files)
        graph_instance.download_file_by_id.return_value = b"restricted content"
        mock_graph_cls.return_value = graph_instance

        mock_upload.return_value = {"status": True, "id": "file-id-1"}

        result = await import_sharepoint_folder(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.imported == 1
        assert result.failed == 0
        graph_instance.download_file.assert_not_called()
        graph_instance.download_file_by_id.assert_called_once_with(DRIVE_ID, "f1")

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_knowledge_not_found(self, mock_kb):
        """Invalid KB ID → 400."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=None)

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_folder(
                request=request,
                id="nonexistent",
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.AccessGrants")
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_no_write_access(self, mock_kb, mock_access):
        """User without write access → 400."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge(user_id="other-user"))
        mock_access.has_access = AsyncMock(return_value=False)

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_folder(
                request=request,
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    async def test_no_oauth_session(self, mock_oauth, mock_kb):
        """No Microsoft OAuth session → 401."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=None)

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_folder(
                request=request,
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 401
        assert "Microsoft" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_graph_401_expired_token(self, mock_graph_cls, mock_oauth, mock_kb):
        """Graph API returns 401 → clear re-login message."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        resp = httpx.Response(401, request=httpx.Request("GET", "https://graph.microsoft.com"))
        graph_instance.list_folder.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=resp.request, response=resp
        )
        mock_graph_cls.return_value = graph_instance

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_folder(
                request=request,
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 401
        assert "expired" in str(exc_info.value.detail).lower() or "re-login" in str(exc_info.value.detail).lower()

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_graph_403_missing_scope(self, mock_graph_cls, mock_oauth, mock_kb):
        """Graph API returns 403 → message about Files.Read.All."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        resp = httpx.Response(403, request=httpx.Request("GET", "https://graph.microsoft.com"))
        graph_instance.list_folder.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=resp.request, response=resp
        )
        mock_graph_cls.return_value = graph_instance

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_folder(
                request=request,
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 403
        assert "Files.Read.All" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_empty_folder(self, mock_graph_cls, mock_oauth, mock_kb):
        """Empty folder → success with 0 files."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=[], folder_name="Empty")
        mock_graph_cls.return_value = graph_instance

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        assert result.total_files == 0
        assert result.imported == 0
        assert result.failed == 0

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_only_subfolders(self, mock_graph_cls, mock_oauth, mock_kb):
        """Folder with only subfolders → 0 files, skipped_folders populated."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(
            files=[], skipped_folders=["Sub1", "Sub2"]
        )
        mock_graph_cls.return_value = graph_instance

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        assert result.total_files == 0
        assert result.imported == 0
        assert result.skipped_folders == ["Sub1", "Sub2"]

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_file_without_download_url(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """File with no download URL → reported as error, not crash."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        no_url_file = GraphFileItem(
            id="f-nourl", name="broken.pdf", size=100,
            content_type="application/pdf", download_url=None,
        )
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=[no_url_file])
        mock_graph_cls.return_value = graph_instance

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        assert result.total_files == 1
        assert result.imported == 0
        assert result.failed == 1
        assert "download URL" in result.errors[0].error

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_graph_client_receives_correct_token(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """Verify GraphClient is instantiated with the token from oauth_session."""
        from open_webui.routers.knowledge import import_sharepoint_folder, SharePointImportForm

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())

        mock_kb.add_file_to_knowledge_by_id = AsyncMock()

        mock_kb.update_knowledge_by_id = AsyncMock()

        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session(access_token="my-specific-token")
        )

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=[])
        mock_graph_cls.return_value = graph_instance

        request = _make_request(access_token="my-specific-token")
        user = _make_user()
        db = MagicMock()

        await import_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=user,
            db=db,
        )

        mock_graph_cls.assert_called_once_with("my-specific-token")


class TestSharePointReimport:
    """Tests for POST /knowledge/{id}/sharepoint/reimport"""

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_reimport_uses_stored_source(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """Re-import reads drive_id/item_id from KB metadata."""
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        kb = _make_knowledge()
        kb.meta = {
            "sharepoint_source": {
                "drive_id": DRIVE_ID,
                "item_id": ITEM_ID,
                "folder_name": "OriginalFolder",
                "folder_path": "/root:/Documents",
                "last_imported_at": 1000000,
            }
        }
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(return_value=_make_oauth_session())

        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(
            files=[
                GraphFileItem(
                    id="f1", name="updated.pdf", size=2048,
                    content_type="application/pdf",
                    download_url="https://cdn.example.com/updated.pdf",
                ),
            ]
        )
        graph_instance.download_file.return_value = b"new content"
        mock_graph_cls.return_value = graph_instance

        mock_upload.side_effect = None; mock_upload.return_value = {"status": True, "id": "file-reimport-1"}

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        result = await reimport_sharepoint_folder(
            request=request,
            id=KNOWLEDGE_ID,
            user=user,
            db=db,
        )

        assert result.imported == 1
        graph_instance.list_folder.assert_called_once_with(DRIVE_ID, ITEM_ID)

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_reimport_no_source_configured(self, mock_kb):
        """Re-import without prior import → 400."""
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        kb = _make_knowledge()
        kb.meta = {}
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await reimport_sharepoint_folder(
                request=request,
                id=KNOWLEDGE_ID,
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 400
        assert "No SharePoint source" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_reimport_kb_not_found(self, mock_kb):
        """Re-import with invalid KB → 400."""
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=None)

        request = _make_request()
        user = _make_user()
        db = MagicMock()

        with pytest.raises(Exception) as exc_info:
            await reimport_sharepoint_folder(
                request=request,
                id="nonexistent",
                user=user,
                db=db,
            )
        assert exc_info.value.status_code == 400


class TestDisplayFilename:
    """Flattening of subfolder paths into the uploaded filename."""

    def test_root_file_unchanged(self):
        from open_webui.routers.knowledge import _build_display_filename

        assert _build_display_filename("", "doc.pdf") == "doc.pdf"

    def test_single_subfolder(self):
        from open_webui.routers.knowledge import _build_display_filename

        assert (
            _build_display_filename("Invoices/", "report.pdf")
            == "Invoices › report.pdf"
        )

    def test_nested_subfolders(self):
        from open_webui.routers.knowledge import _build_display_filename

        assert (
            _build_display_filename("A/B/C/", "deep.pdf")
            == "A › B › C › deep.pdf"
        )

    def test_overflow_truncates_from_front(self):
        from open_webui.routers.knowledge import (
            _build_display_filename,
            SHAREPOINT_FILENAME_MAX,
        )

        long_path = "/".join([f"Folder{i}" for i in range(100)]) + "/"
        result = _build_display_filename(long_path, "file.pdf")

        assert len(result) <= SHAREPOINT_FILENAME_MAX
        assert result.startswith("…")
        assert result.endswith("file.pdf")


class TestPathPrefixFlow:
    """Subfolder path must be flattened into the filename passed to upload_file_handler."""

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_subfolder_file_gets_path_prefix(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        from open_webui.routers.knowledge import (
            import_sharepoint_folder,
            SharePointImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        nested_file = GraphFileItem(
            id="f1",
            name="jan.pdf",
            size=1024,
            content_type="application/pdf",
            download_url="https://cdn.example.com/jan.pdf",
            path="Invoices/2024/",
        )
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=[nested_file])
        graph_instance.download_file.return_value = b"pdf bytes"
        mock_graph_cls.return_value = graph_instance

        mock_upload.return_value = {"status": True, "id": "file-1"}

        await import_sharepoint_folder(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=_make_user(),
            db=MagicMock(),
        )

        upload_file_arg = mock_upload.call_args.kwargs["file"]
        assert upload_file_arg.filename == "Invoices › 2024 › jan.pdf"

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_truncated_flag_propagates_to_response(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        from open_webui.routers.knowledge import (
            import_sharepoint_folder,
            SharePointImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        listing = GraphFolderListing(
            folder_name="Huge",
            folder_path="/",
            drive_id=DRIVE_ID,
            item_id=ITEM_ID,
            files=[],
            truncated=True,
        )
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = listing
        mock_graph_cls.return_value = graph_instance

        result = await import_sharepoint_folder(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.truncated is True


SITE_ID = "contoso.sharepoint.com,site-guid,web-guid"


def _make_site_listing(files=None, site_name="Contoso"):
    from open_webui.utils.graph_client import GraphDriveInfo, GraphSiteListing

    if files is None:
        files = [
            GraphFileItem(
                id="f1",
                name="brief.pdf",
                size=1024,
                content_type="application/pdf",
                download_url="https://cdn.example.com/brief.pdf",
                path="Documents/",
            )
        ]
    return GraphSiteListing(
        site_id=SITE_ID,
        site_name=site_name,
        site_url=f"https://contoso.sharepoint.com/sites/{site_name.lower()}",
        drives=[
            GraphDriveInfo(
                id="d1", name="Documents", drive_type="documentLibrary", root_item_id="r1"
            )
        ],
        files=files,
    )


class TestSharePointSiteImport:
    """POST /knowledge/{id}/sharepoint/import-site"""

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_imports_all_site_files_and_persists_source(
        self, mock_process, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        from open_webui.routers.knowledge import (
            import_sharepoint_site,
            SharePointSiteImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_kb.update_knowledge_by_id = AsyncMock()
        mock_kb.get_file_metadatas_by_id = AsyncMock(return_value=[])
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        graph_instance = AsyncMock()
        graph_instance.list_site.return_value = _make_site_listing()
        graph_instance.download_file.return_value = b"pdf bytes"
        mock_graph_cls.return_value = graph_instance

        mock_upload.return_value = {"status": True, "id": "file-id-1"}

        result = await import_sharepoint_site(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointSiteImportForm(site_id=SITE_ID),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.imported == 1
        assert result.folder_name == "Contoso"
        upload_file_arg = mock_upload.call_args.kwargs["file"]
        assert upload_file_arg.filename == "Documents › brief.pdf"

        persisted = mock_kb.update_knowledge_by_id.call_args.kwargs["form_data"]
        assert persisted.meta["sharepoint_source"]["type"] == "site"
        assert persisted.meta["sharepoint_source"]["site_id"] == SITE_ID
        assert persisted.meta["sharepoint_source"]["drive_count"] == 1

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_graph_401_surfaces_as_401(
        self, mock_graph_cls, mock_oauth, mock_kb
    ):
        from open_webui.routers.knowledge import (
            import_sharepoint_site,
            SharePointSiteImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        graph_instance = AsyncMock()
        fake_resp = MagicMock()
        fake_resp.status_code = 401
        graph_instance.list_site.side_effect = httpx.HTTPStatusError(
            "expired", request=MagicMock(), response=fake_resp
        )
        mock_graph_cls.return_value = graph_instance

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_site(
                request=_make_request(),
                id=KNOWLEDGE_ID,
                form_data=SharePointSiteImportForm(site_id=SITE_ID),
                user=_make_user(),
                db=MagicMock(),
            )
        assert exc_info.value.status_code == 401


class TestReimportDispatch:
    """/sharepoint/reimport routes to folder or site import based on meta.type."""

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.import_sharepoint_site", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_site_source_dispatches_to_site_import(
        self, mock_kb, mock_site_import
    ):
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        kb = _make_knowledge()
        kb.meta = {
            "sharepoint_source": {
                "type": "site",
                "site_id": SITE_ID,
                "site_name": "Contoso",
            }
        }
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)
        mock_site_import.return_value = MagicMock()

        await reimport_sharepoint_folder(
            request=_make_request(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
        )

        mock_site_import.assert_awaited_once()
        call = mock_site_import.call_args.kwargs
        assert call["form_data"].site_id == SITE_ID

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.import_sharepoint_folder", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_folder_source_without_type_uses_folder_import(
        self, mock_kb, mock_folder_import
    ):
        """Back-compat: old metadata (no `type` key) is treated as folder."""
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        kb = _make_knowledge()
        kb.meta = {
            "sharepoint_source": {
                "drive_id": DRIVE_ID,
                "item_id": ITEM_ID,
                "folder_name": "Docs",
            }
        }
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)
        mock_folder_import.return_value = MagicMock()

        await reimport_sharepoint_folder(
            request=_make_request(), id=KNOWLEDGE_ID, user=_make_user(), db=MagicMock()
        )

        mock_folder_import.assert_awaited_once()
        call = mock_folder_import.call_args.kwargs
        assert call["form_data"].drive_id == DRIVE_ID

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_no_source_raises_400(self, mock_kb):
        from open_webui.routers.knowledge import reimport_sharepoint_folder

        kb = _make_knowledge()
        kb.meta = {}
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)

        with pytest.raises(Exception) as exc_info:
            await reimport_sharepoint_folder(
                request=_make_request(),
                id=KNOWLEDGE_ID,
                user=_make_user(),
                db=MagicMock(),
            )
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Per-file streaming endpoints (preferred over bulk import)
# ---------------------------------------------------------------------------


class TestSharePointListFolder:
    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_returns_flat_file_entries_with_display_name(
        self, mock_graph_cls, mock_oauth, mock_kb
    ):
        from open_webui.routers.knowledge import (
            list_sharepoint_folder,
            SharePointImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        files = [
            GraphFileItem(
                id="f1", name="report.pdf", size=1024,
                content_type="application/pdf",
                download_url="https://cdn.example.com/report.pdf",
                drive_id=DRIVE_ID,
                path="Invoices/2024/",
            ),
        ]
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=files)
        mock_graph_cls.return_value = graph_instance

        result = await list_sharepoint_folder(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.knowledge_id == KNOWLEDGE_ID
        assert len(result.files) == 1
        entry = result.files[0]
        assert entry.drive_id == DRIVE_ID
        assert entry.item_id == "f1"
        assert entry.path == "Invoices/2024/"
        # Path flattened into display name via SHAREPOINT_PATH_SEPARATOR
        assert "report.pdf" in entry.display_name
        assert "Invoices" in entry.display_name

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_size_limit_blocks_oversized_listing(
        self, mock_graph_cls, mock_oauth, mock_kb
    ):
        """Cumulative file size > SHAREPOINT_IMPORT_MAX_TOTAL_SIZE_MB → HTTP 413."""
        from open_webui.routers.knowledge import (
            list_sharepoint_folder,
            SharePointImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        # 3 files × 80 MB = 240 MB; limit is 200 MB.
        big = 80 * 1024 * 1024
        files = [
            GraphFileItem(
                id=f"f{i}", name=f"big{i}.pdf", size=big,
                content_type="application/pdf",
                download_url=f"https://cdn.example.com/big{i}.pdf",
                drive_id=DRIVE_ID,
            )
            for i in range(3)
        ]
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=files)
        mock_graph_cls.return_value = graph_instance

        with pytest.raises(Exception) as exc_info:
            await list_sharepoint_folder(
                request=_make_request(sharepoint_import_max_total_size_mb=200),
                id=KNOWLEDGE_ID,
                form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
                user=_make_user(),
                db=MagicMock(),
            )
        assert exc_info.value.status_code == 413
        assert "200 MB" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_size_limit_zero_means_unlimited(
        self, mock_graph_cls, mock_oauth, mock_kb
    ):
        """limit_mb=0 (or None) → never raises, even for huge listings."""
        from open_webui.routers.knowledge import (
            list_sharepoint_folder,
            SharePointImportForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        huge = 1024 * 1024 * 1024  # 1 GB per file
        files = [
            GraphFileItem(
                id="f1", name="huge.pdf", size=huge,
                content_type="application/pdf",
                download_url="https://cdn.example.com/huge.pdf",
                drive_id=DRIVE_ID,
            ),
        ]
        graph_instance = AsyncMock()
        graph_instance.list_folder.return_value = _make_folder_listing(files=files)
        mock_graph_cls.return_value = graph_instance

        result = await list_sharepoint_folder(
            request=_make_request(sharepoint_import_max_total_size_mb=0),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportForm(drive_id=DRIVE_ID, item_id=ITEM_ID),
            user=_make_user(),
            db=MagicMock(),
        )
        assert len(result.files) == 1
        # No download happened on the list endpoint.
        graph_instance.download_file.assert_not_called()
        # Source payload mirrors what the bulk endpoint would persist.
        assert result.source["type"] == "folder"
        assert result.source["drive_id"] == DRIVE_ID


class TestSharePointImportFile:
    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    @patch(f"{_KNOWLEDGE_MOD}.process_file", new_callable=AsyncMock)
    async def test_imports_one_file_via_metadata_then_download(
        self,
        mock_process,
        mock_upload,
        mock_graph_cls,
        mock_oauth,
        mock_kb,
    ):
        from open_webui.routers.knowledge import (
            import_sharepoint_file,
            SharePointImportFileForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_kb.add_file_to_knowledge_by_id = AsyncMock()
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        graph_instance = AsyncMock()
        graph_instance.get_file_metadata.return_value = GraphFileItem(
            id="f1", name="restricted.pdf", size=2048,
            content_type="application/pdf",
            download_url=None,           # tenant strips downloadUrl
            drive_id=DRIVE_ID,
            path="",
        )
        graph_instance.download_file_by_id.return_value = b"file content"
        mock_graph_cls.return_value = graph_instance

        mock_upload.return_value = {"status": True, "id": "file-id-1"}

        result = await import_sharepoint_file(
            request=_make_request(),
            id=KNOWLEDGE_ID,
            form_data=SharePointImportFileForm(
                drive_id=DRIVE_ID, item_id="f1", path=""
            ),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result.knowledge_id == KNOWLEDGE_ID
        assert result.file_id == "file-id-1"
        assert result.filename == "restricted.pdf"
        graph_instance.get_file_metadata.assert_awaited_once_with(
            DRIVE_ID, "f1", ""
        )
        # downloadUrl was None → fallback path used.
        graph_instance.download_file.assert_not_called()
        graph_instance.download_file_by_id.assert_awaited_once_with(DRIVE_ID, "f1")
        mock_upload.assert_awaited_once()
        mock_process.assert_awaited_once()
        mock_kb.add_file_to_knowledge_by_id.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    async def test_metadata_403_surfaces_as_403(
        self, mock_graph_cls, mock_oauth, mock_kb
    ):
        """Graph 403 on metadata fetch is translated, not silently swallowed."""
        from open_webui.routers.knowledge import (
            import_sharepoint_file,
            SharePointImportFileForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        response_403 = MagicMock(status_code=403)
        response_403.json.return_value = {"error": {"code": "accessDenied"}}
        graph_instance = AsyncMock()
        graph_instance.get_file_metadata.side_effect = httpx.HTTPStatusError(
            "forbidden", request=MagicMock(), response=response_403
        )
        mock_graph_cls.return_value = graph_instance

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_file(
                request=_make_request(),
                id=KNOWLEDGE_ID,
                form_data=SharePointImportFileForm(
                    drive_id=DRIVE_ID, item_id="f1", path=""
                ),
                user=_make_user(),
                db=MagicMock(),
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    @patch(f"{_BACKEND_MOD}.OAuthSessions")
    @patch(f"{_BACKEND_MOD}.GraphClient")
    @patch(f"{_KNOWLEDGE_MOD}.upload_file_handler", new_callable=AsyncMock)
    async def test_download_failure_returns_500(
        self, mock_upload, mock_graph_cls, mock_oauth, mock_kb
    ):
        """If the download itself fails, the endpoint returns 500 with the cause."""
        from open_webui.routers.knowledge import (
            import_sharepoint_file,
            SharePointImportFileForm,
        )

        mock_kb.get_knowledge_by_id = AsyncMock(return_value=_make_knowledge())
        mock_oauth.get_session_by_provider_and_user_id = AsyncMock(
            return_value=_make_oauth_session()
        )

        graph_instance = AsyncMock()
        graph_instance.get_file_metadata.return_value = GraphFileItem(
            id="f1", name="boom.pdf", size=10,
            content_type="application/pdf",
            download_url="https://cdn.example.com/boom.pdf",
            drive_id=DRIVE_ID,
        )
        graph_instance.download_file.side_effect = RuntimeError("network down")
        mock_graph_cls.return_value = graph_instance

        with pytest.raises(Exception) as exc_info:
            await import_sharepoint_file(
                request=_make_request(),
                id=KNOWLEDGE_ID,
                form_data=SharePointImportFileForm(
                    drive_id=DRIVE_ID, item_id="f1", path=""
                ),
                user=_make_user(),
                db=MagicMock(),
            )
        assert exc_info.value.status_code == 500
        assert "boom.pdf" in str(exc_info.value.detail)


class TestSharePointPersistSource:
    @pytest.mark.asyncio
    @patch(f"{_KNOWLEDGE_MOD}.Knowledges")
    async def test_persists_source_with_timestamp(self, mock_kb):
        from open_webui.routers.knowledge import (
            persist_sharepoint_source,
            SharePointPersistSourceForm,
        )

        kb = _make_knowledge()
        kb.meta = {}
        mock_kb.get_knowledge_by_id = AsyncMock(return_value=kb)
        mock_kb.update_knowledge_by_id = AsyncMock()

        result = await persist_sharepoint_source(
            id=KNOWLEDGE_ID,
            form_data=SharePointPersistSourceForm(
                source={"type": "folder", "drive_id": DRIVE_ID, "item_id": ITEM_ID}
            ),
            user=_make_user(),
            db=MagicMock(),
        )

        assert result == {"ok": True}
        mock_kb.update_knowledge_by_id.assert_awaited_once()
        form_data = mock_kb.update_knowledge_by_id.call_args.kwargs["form_data"]
        assert form_data.meta["sharepoint_source"]["type"] == "folder"
        # Endpoint stamps last_imported_at server-side.
        assert "last_imported_at" in form_data.meta["sharepoint_source"]


# ---------------------------------------------------------------------------
# Graph credential resolution edge cases (moved to utils/sharepoint_backend.py)
# ---------------------------------------------------------------------------


class TestMicrosoftAccessTokenHelper:
    """Edge cases for the Graph credential path.

    Formerly `knowledge._get_microsoft_access_token`, which returned a bearer string.
    It now lives in `utils.sharepoint_backend._graph_backend` and returns a ready
    GraphClient instead. The policy under test -- when to 500, when to 401, never to
    delete a session on refresh failure -- is unchanged.
    """

    @pytest.mark.asyncio
    async def test_no_oauth_manager_raises_500(self):
        """app.state has no oauth_client_manager -> HTTP 500."""
        from open_webui.utils.sharepoint_backend import _graph_backend
        from fastapi import HTTPException

        request = MagicMock()
        state = MagicMock(spec=[])  # no attributes on spec -> getattr returns default
        request.app.state = state

        with pytest.raises(HTTPException) as exc_info:
            await _graph_backend(request, _make_user(), MagicMock())

        assert exc_info.value.status_code == 500
        assert "not initialised" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_oauth_token_returns_none_raises_401(self):
        """get_oauth_token returns None (refresh failed) -> HTTP 401."""
        from open_webui.utils.sharepoint_backend import _graph_backend
        from fastapi import HTTPException

        request = _make_request(access_token=None)

        with pytest.raises(HTTPException) as exc_info:
            await _graph_backend(request, _make_user(), MagicMock())

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_oauth_token_returns_dict_without_access_token_raises_401(self):
        """get_oauth_token returns dict missing access_token key -> HTTP 401."""
        from open_webui.utils.sharepoint_backend import _graph_backend
        from fastapi import HTTPException

        request = _make_request()
        request.app.state.oauth_manager.get_oauth_token = AsyncMock(
            return_value={"token_type": "Bearer"}
        )

        with pytest.raises(HTTPException) as exc_info:
            await _graph_backend(request, _make_user(), MagicMock())

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_failure_does_not_delete_session(self):
        """When get_oauth_token returns None, OAuthSessions.delete_session_by_id
        must NOT be called — transient failures must not force re-linking."""
        from open_webui.utils.sharepoint_backend import _graph_backend
        from fastapi import HTTPException

        request = _make_request(access_token=None)

        mock_oauth_sessions = MagicMock()
        mock_oauth_sessions.delete_session_by_id = AsyncMock()

        with patch(
            "open_webui.utils.sharepoint_backend.OAuthSessions", mock_oauth_sessions
        ):
            with pytest.raises(HTTPException):
                await _graph_backend(request, _make_user(), MagicMock())

        mock_oauth_sessions.delete_session_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_cookie_falls_back_to_newest_provider_session(self):
        """No oauth_session_id cookie → use newest stored Microsoft session."""
        from open_webui.utils.sharepoint_backend import _graph_backend

        request = _make_request(session_cookie=None)
        fallback_session = MagicMock(id="fallback-session-id")

        mock_oauth_sessions = MagicMock()
        mock_oauth_sessions.get_session_by_provider_and_user_id = AsyncMock(
            return_value=fallback_session
        )

        with patch(
            "open_webui.utils.sharepoint_backend.OAuthSessions", mock_oauth_sessions
        ):
            backend = await _graph_backend(
                request, _make_user(), MagicMock()
            )

        assert backend.headers["Authorization"] == "Bearer graph-token-123"
        request.app.state.oauth_manager.get_oauth_token.assert_awaited_once_with(
            USER_ID, "fallback-session-id"
        )

    @pytest.mark.asyncio
    async def test_no_cookie_and_no_stored_session_raises_401(self):
        """Cookie missing AND no stored MS session → HTTP 401 with re-login hint."""
        from open_webui.utils.sharepoint_backend import _graph_backend
        from fastapi import HTTPException

        request = _make_request(session_cookie=None)
        mock_oauth_sessions = MagicMock()
        mock_oauth_sessions.get_session_by_provider_and_user_id = AsyncMock(
            return_value=None
        )

        with patch(
            "open_webui.utils.sharepoint_backend.OAuthSessions", mock_oauth_sessions
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _graph_backend(
                    request, _make_user(), MagicMock()
                )

        assert exc_info.value.status_code == 401
        assert "log in with Microsoft SSO" in exc_info.value.detail


class TestPickerRouteShapes:
    """On-prem ids that may contain '/' must never travel as FastAPI path parameters.

    uvicorn percent-decodes the request path before routing, so an id encoded as
    `%2Fwissen%2FKIS Trainingsvideos` is back to `/wissen/KIS Trainingsvideos` by the time
    the router looks at it and no route matches. The 404 is answered with the SPA's
    index.html, which the frontend reports as `Unexpected token '<'`.
    """

    def test_no_route_takes_site_id_as_path_parameter(self):
        from open_webui.routers.knowledge import router

        offenders = [r.path for r in router.routes if "{site_id}" in r.path]
        assert offenders == [], f"site_id must be a query parameter, not a path segment: {offenders}"

    def test_site_drives_route_exists(self):
        from open_webui.routers.knowledge import router

        assert "/sharepoint/site-drives" in [r.path for r in router.routes]
