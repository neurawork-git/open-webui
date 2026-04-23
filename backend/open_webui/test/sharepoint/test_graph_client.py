"""Unit tests for GraphClient — Microsoft Graph API client."""

import pytest
import httpx

from open_webui.utils.graph_client import (
    GraphClient,
    GraphFolderListing,
    GRAPH_BASE,
)


def _make_graph_item(name: str, is_folder: bool = False, size: int = 1024, item_id: str | None = None):
    """Helper to create a Graph API item dict."""
    resolved_id = item_id or f"id-{name}"
    item = {"id": resolved_id, "name": name, "size": size}
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
    async def test_single_page_files_only(self):
        """Files at root level are returned with empty path."""

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
                            _make_graph_item("notes.docx"),
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert isinstance(result, GraphFolderListing)
        assert result.folder_name == "TestFolder"
        assert len(result.files) == 2
        assert result.files[0].name == "report.pdf"
        assert result.files[0].path == ""
        assert result.files[0].download_url == "https://cdn.example.com/report.pdf"
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_recursive_walk_captures_subfolder_files(self):
        """Subfolders are walked recursively; each file carries its relative path."""

        sub_id = "sub-id-1"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/drives/{self.DRIVE}/items/{self.FOLDER}":
                return httpx.Response(
                    200, json={"name": "Root", "parentReference": {"path": "/"}}
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("top.pdf"),
                            _make_graph_item("Invoices", is_folder=True, item_id=sub_id),
                        ]
                    },
                )
            if f"/items/{sub_id}/children" in url:
                return httpx.Response(
                    200,
                    json={"value": [_make_graph_item("jan.pdf")]},
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert [f.name for f in result.files] == ["top.pdf", "jan.pdf"]
        assert result.files[0].path == ""
        assert result.files[1].path == "Invoices/"
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_deeply_nested_path(self):
        """Path accumulates across multiple nesting levels."""

        sub1 = "sub1"
        sub2 = "sub2"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/drives/{self.DRIVE}/items/{self.FOLDER}":
                return httpx.Response(
                    200, json={"name": "Root", "parentReference": {"path": "/"}}
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("A", is_folder=True, item_id=sub1),
                        ]
                    },
                )
            if f"/items/{sub1}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("B", is_folder=True, item_id=sub2),
                        ]
                    },
                )
            if f"/items/{sub2}/children" in url:
                return httpx.Response(
                    200,
                    json={"value": [_make_graph_item("deep.pdf")]},
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert len(result.files) == 1
        assert result.files[0].name == "deep.pdf"
        assert result.files[0].path == "A/B/"

    @pytest.mark.asyncio
    async def test_truncation_at_max_files(self):
        """Recursion stops at max_files, truncated=True."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/drives/{self.DRIVE}/items/{self.FOLDER}":
                return httpx.Response(
                    200, json={"name": "Big", "parentReference": {"path": "/"}}
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("a.pdf"),
                            _make_graph_item("b.pdf"),
                            _make_graph_item("c.pdf"),
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER, max_files=2)

        assert len(result.files) == 2
        assert result.truncated is True

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
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_only_folders_walks_them(self):
        """A folder containing only subfolders (all empty) → 0 files, no skipped list."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/children" not in url and f"/items/{self.FOLDER}" in url:
                return httpx.Response(
                    200,
                    json={"name": "OnlyFolders", "parentReference": {"path": "/"}},
                )
            if f"/items/{self.FOLDER}/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("Sub1", is_folder=True, item_id="s1"),
                            _make_graph_item("Sub2", is_folder=True, item_id="s2"),
                        ]
                    },
                )
            if "/items/s1/children" in url or "/items/s2/children" in url:
                return httpx.Response(200, json={"value": []})
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_folder(self.DRIVE, self.FOLDER)

        assert len(result.files) == 0
        assert result.skipped_folders == []

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
