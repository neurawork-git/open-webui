"""Unit tests for GraphClient — Microsoft Graph API client."""

import pytest
import httpx

from open_webui.utils.graph_client import (
    GraphClient,
    GraphFolderListing,
    GRAPH_BASE,
)


def _make_graph_item(name: str, is_folder: bool = False, size: int = 1024):
    """Helper to create a Graph API item dict."""
    item = {"id": f"id-{name}", "name": name, "size": size}
    if is_folder:
        item["folder"] = {"childCount": 3}
    else:
        item["file"] = {"mimeType": "application/pdf"}
        item["@microsoft.graph.downloadUrl"] = f"https://cdn.example.com/{name}"
    return item


def _make_client(handler) -> GraphClient:
    """Create a GraphClient with a mocked HTTP transport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return GraphClient("test-token", http_client=http_client)


# ---------------------------------------------------------------------------
# list_folder tests
# ---------------------------------------------------------------------------


class TestListFolder:
    DRIVE = "drive-1"
    FOLDER = "folder-1"

    @pytest.mark.asyncio
    async def test_single_page_mixed_items(self):
        """Files are returned, folders are skipped."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/drives/{self.DRIVE}/items/{self.FOLDER}":
                return httpx.Response(
                    200,
                    json={
                        "name": "TestFolder",
                        "parentReference": {"path": "/drives/drive-1/root:/Documents"},
                    },
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("report.pdf"),
                            _make_graph_item("Subfolder", is_folder=True),
                            _make_graph_item("notes.docx"),
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert isinstance(result, GraphFolderListing)
        assert result.folder_name == "TestFolder"
        assert result.drive_id == self.DRIVE
        assert result.item_id == self.FOLDER
        assert len(result.files) == 2
        assert result.files[0].name == "report.pdf"
        assert result.files[1].name == "notes.docx"
        assert result.files[0].download_url == "https://cdn.example.com/report.pdf"
        assert result.skipped_folders == ["Subfolder"]

    @pytest.mark.asyncio
    async def test_pagination(self):
        """Follows @odata.nextLink for multi-page results."""
        page2_url = "https://graph.microsoft.com/v1.0/next-page-token"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/drives/{self.DRIVE}/items/{self.FOLDER}":
                return httpx.Response(
                    200, json={"name": "BigFolder", "parentReference": {"path": "/"}}
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [_make_graph_item("file1.pdf")],
                        "@odata.nextLink": page2_url,
                    },
                )
            if url == page2_url:
                return httpx.Response(
                    200,
                    json={"value": [_make_graph_item("file2.pdf")]},
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert len(result.files) == 2
        assert result.files[0].name == "file1.pdf"
        assert result.files[1].name == "file2.pdf"

    @pytest.mark.asyncio
    async def test_empty_folder(self):
        """Empty folder returns zero files."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/children" not in url and f"/items/{self.FOLDER}" in url:
                return httpx.Response(
                    200, json={"name": "Empty", "parentReference": {"path": "/"}}
                )
            if "/children" in url:
                return httpx.Response(200, json={"value": []})
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert len(result.files) == 0
        assert len(result.skipped_folders) == 0

    @pytest.mark.asyncio
    async def test_only_folders(self):
        """Folder containing only subfolders → 0 files, populated skipped_folders."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/children" not in url and f"/items/{self.FOLDER}" in url:
                return httpx.Response(
                    200, json={"name": "OnlyFolders", "parentReference": {"path": "/"}}
                )
            if "/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("Sub1", is_folder=True),
                            _make_graph_item("Sub2", is_folder=True),
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert len(result.files) == 0
        assert result.skipped_folders == ["Sub1", "Sub2"]

    @pytest.mark.asyncio
    async def test_401_raises(self):
        """Expired token → httpx.HTTPStatusError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.list_folder(self.DRIVE, self.FOLDER)
        assert exc_info.value.response.status_code == 401

    @pytest.mark.asyncio
    async def test_403_raises(self):
        """Missing scopes → httpx.HTTPStatusError."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": {"code": "AccessDenied"}})

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.list_folder(self.DRIVE, self.FOLDER)
        assert exc_info.value.response.status_code == 403

    @pytest.mark.asyncio
    async def test_auth_header_sent(self):
        """Verify Authorization header is passed on all requests."""
        captured_headers = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            url = str(request.url)
            if "/children" not in url:
                return httpx.Response(
                    200, json={"name": "F", "parentReference": {"path": "/"}}
                )
            return httpx.Response(200, json={"value": []})

        client = _make_client(handler)
        await client.list_folder(self.DRIVE, self.FOLDER)

        for h in captured_headers:
            assert h.get("authorization") == "Bearer test-token"


# ---------------------------------------------------------------------------
# download_file tests
# ---------------------------------------------------------------------------


class TestDownloadFile:
    @pytest.mark.asyncio
    async def test_download_returns_bytes(self):
        content = b"PDF file content here"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=content)

        client = _make_client(handler)
        result = await client.download_file("https://cdn.example.com/file.pdf")
        assert result == content

    @pytest.mark.asyncio
    async def test_download_raises_on_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.download_file("https://cdn.example.com/missing.pdf")
