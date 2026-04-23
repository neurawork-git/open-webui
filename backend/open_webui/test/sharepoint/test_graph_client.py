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


class TestListSite:
    SITE = "contoso.sharepoint.com,site-guid,web-guid"

    @pytest.mark.asyncio
    async def test_single_drive_recursive(self):
        """One drive with a subfolder → files keep drive-prefixed paths."""

        drive_id = "drv-1"
        root_id = "root-1"
        sub_id = "sub-1"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/sites/{self.SITE}":
                return httpx.Response(
                    200,
                    json={
                        "id": self.SITE,
                        "displayName": "Contoso",
                        "name": "contoso",
                        "webUrl": "https://contoso.sharepoint.com/sites/contoso",
                    },
                )
            if url == f"{GRAPH_BASE}/sites/{self.SITE}/drives":
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": drive_id,
                                "name": "Documents",
                                "driveType": "documentLibrary",
                            }
                        ]
                    },
                )
            if f"/drives/{drive_id}/root" in url:
                return httpx.Response(200, json={"id": root_id})
            if f"/items/{root_id}/children" in url:
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
                    200, json={"value": [_make_graph_item("q1.pdf")]}
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_site(self.SITE)

        assert result.site_name == "Contoso"
        assert result.site_url == "https://contoso.sharepoint.com/sites/contoso"
        assert len(result.drives) == 1
        assert result.drives[0].name == "Documents"
        assert result.drives[0].root_item_id == root_id
        assert [f.path for f in result.files] == ["Documents/", "Documents/Invoices/"]
        assert [f.name for f in result.files] == ["top.pdf", "q1.pdf"]
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_multiple_drives(self):
        """Multiple drives → each drive's name prefixes its files."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/sites/{self.SITE}":
                return httpx.Response(
                    200,
                    json={"id": self.SITE, "displayName": "S", "webUrl": "https://x"},
                )
            if url == f"{GRAPH_BASE}/sites/{self.SITE}/drives":
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {"id": "d1", "name": "Documents"},
                            {"id": "d2", "name": "Shared"},
                        ]
                    },
                )
            if "/drives/d1/root" in url:
                return httpx.Response(200, json={"id": "r1"})
            if "/drives/d2/root" in url:
                return httpx.Response(200, json={"id": "r2"})
            if "/items/r1/children" in url:
                return httpx.Response(
                    200, json={"value": [_make_graph_item("a.pdf")]}
                )
            if "/items/r2/children" in url:
                return httpx.Response(
                    200, json={"value": [_make_graph_item("b.pdf")]}
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_site(self.SITE)

        assert len(result.drives) == 2
        assert {f.path for f in result.files} == {"Documents/", "Shared/"}

    @pytest.mark.asyncio
    async def test_truncation_across_drives(self):
        """Truncation inside one drive prevents walking remaining drives."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/sites/{self.SITE}":
                return httpx.Response(200, json={"id": self.SITE, "displayName": "S"})
            if url == f"{GRAPH_BASE}/sites/{self.SITE}/drives":
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {"id": "d1", "name": "Big"},
                            {"id": "d2", "name": "Small"},
                        ]
                    },
                )
            if "/drives/d1/root" in url:
                return httpx.Response(200, json={"id": "r1"})
            if "/drives/d2/root" in url:
                return httpx.Response(200, json={"id": "r2"})
            if "/items/r1/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            _make_graph_item("a.pdf"),
                            _make_graph_item("b.pdf"),
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.list_site(self.SITE, max_files=1)

        assert result.truncated is True
        assert len(result.files) == 1
        # Only first drive got walked; second drive not enumerated.


class TestSearchSites:
    @pytest.mark.asyncio
    async def test_search_returns_trimmed_dicts(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            assert "/sites?" in url
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "site-1",
                            "name": "contoso",
                            "displayName": "Contoso",
                            "webUrl": "https://contoso.sharepoint.com",
                            "description": "ignored",
                        },
                        {
                            "id": "site-2",
                            "name": "fabrikam",
                            "displayName": "Fabrikam",
                            "webUrl": "https://fabrikam.sharepoint.com",
                        },
                    ]
                },
            )

        client = _make_client(handler)
        results = await client.search_sites("con")

        assert len(results) == 2
        assert results[0] == {
            "id": "site-1",
            "name": "contoso",
            "display_name": "Contoso",
            "web_url": "https://contoso.sharepoint.com",
        }


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
