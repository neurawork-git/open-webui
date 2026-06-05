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


class TestListSitesPaginated:
    @pytest.mark.asyncio
    async def test_first_page_and_follow_next_link(self):
        page2_url = "https://graph.microsoft.com/v1.0/sites?$skiptoken=abc"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == page2_url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "s2",
                                "name": "second",
                                "displayName": "Second Site",
                                "webUrl": "https://x/s2",
                            }
                        ]
                    },
                )
            if url.startswith(f"{GRAPH_BASE}/sites"):
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "s1",
                                "name": "first",
                                "displayName": "First Site",
                                "webUrl": "https://x/s1",
                            }
                        ],
                        "@odata.nextLink": page2_url,
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        page1 = await client.list_sites_paginated()
        assert len(page1["sites"]) == 1
        assert page1["sites"][0]["id"] == "s1"
        assert page1["next_link"] == page2_url

        page2 = await client.list_sites_paginated(next_link=page1["next_link"])
        assert len(page2["sites"]) == 1
        assert page2["sites"][0]["id"] == "s2"
        assert page2["next_link"] is None

    @pytest.mark.asyncio
    async def test_wildcard_default(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"value": []})

        client = _make_client(handler)
        await client.list_sites_paginated()
        assert "search=%2A" in captured["url"] or "search=*" in captured["url"]


class TestListSiteDrivesSummary:
    SITE = "contoso.sharepoint.com,site-guid,web-guid"

    @pytest.mark.asyncio
    async def test_drives_include_size(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == f"{GRAPH_BASE}/sites/{self.SITE}":
                return httpx.Response(
                    200,
                    json={"id": self.SITE, "displayName": "Contoso", "webUrl": "https://x"},
                )
            if url == f"{GRAPH_BASE}/sites/{self.SITE}/drives":
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "d1",
                                "name": "Documents",
                                "driveType": "documentLibrary",
                                "quota": {"used": 12345678},
                            }
                        ]
                    },
                )
            if "/drives/d1/root" in url:
                return httpx.Response(200, json={"id": "r1", "size": 999})
            return httpx.Response(404)

        client = _make_client(handler)
        out = await client.list_site_drives_summary(self.SITE)
        assert out["site_name"] == "Contoso"
        assert len(out["drives"]) == 1
        d = out["drives"][0]
        assert d["total_size"] == 12345678
        assert d["root_item_id"] == "r1"


class TestListFolderChildren:
    DRIVE = "d1"
    ITEM = "i1"

    @pytest.mark.asyncio
    async def test_splits_folders_and_files_with_metadata(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if f"/drives/{self.DRIVE}/items/{self.ITEM}" in url and "/children" not in url:
                return httpx.Response(
                    200, json={"name": "Parent", "size": 1000000}
                )
            if "/children" in url:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "f-a",
                                "name": "SubA",
                                "size": 500000,
                                "folder": {"childCount": 3},
                            },
                            {
                                "id": "file-1",
                                "name": "report.pdf",
                                "size": 2048,
                                "file": {"mimeType": "application/pdf"},
                            },
                        ]
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        out = await client.list_folder_children(self.DRIVE, self.ITEM)
        assert out.parent_name == "Parent"
        assert out.parent_size == 1000000
        assert len(out.folders) == 1 and out.folders[0].name == "SubA"
        assert out.folders[0].size == 500000
        assert out.folders[0].child_count == 3
        assert len(out.files) == 1 and out.files[0].content_type == "application/pdf"

    @pytest.mark.asyncio
    async def test_pagination_next_link(self):
        page2 = "https://graph.microsoft.com/v1.0/next-page"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == page2:
                return httpx.Response(200, json={"value": []})
            if "/children" in url:
                return httpx.Response(
                    200,
                    json={"value": [], "@odata.nextLink": page2},
                )
            if f"/drives/{self.DRIVE}/items/{self.ITEM}" in url:
                return httpx.Response(200, json={"name": "P", "size": 0})
            return httpx.Response(404)

        client = _make_client(handler)
        p1 = await client.list_folder_children(self.DRIVE, self.ITEM)
        assert p1.next_link == page2
        p2 = await client.list_folder_children(self.DRIVE, self.ITEM, next_link=page2)
        assert p2.next_link is None


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


class TestDownloadFileById:
    """Fallback path used when @microsoft.graph.downloadUrl is suppressed."""

    @pytest.mark.asyncio
    async def test_follows_redirect_and_returns_bytes(self):
        content = b"binary content via /content endpoint"
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_urls.append(str(request.url))
            if "/content" in str(request.url):
                # Graph normally 302s to a pre-signed CDN URL.
                return httpx.Response(
                    302, headers={"Location": "https://cdn.example.com/signed"}
                )
            return httpx.Response(200, content=content)

        client = _make_client(handler)
        result = await client.download_file_by_id("drive-1", "item-1")
        assert result == content
        assert any("/content" in u for u in seen_urls)
        assert any("cdn.example.com/signed" in u for u in seen_urls)


class TestGetFileMetadata:
    @pytest.mark.asyncio
    async def test_returns_graph_file_item(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/drives/drive-1/items/item-1" in str(request.url)
            assert "$select=id,name,size,file" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "id": "item-1",
                    "name": "report.pdf",
                    "size": 4096,
                    "file": {"mimeType": "application/pdf"},
                    "@microsoft.graph.downloadUrl": "https://cdn.example.com/report.pdf",
                },
            )

        client = _make_client(handler)
        item = await client.get_file_metadata("drive-1", "item-1", path="Invoices/")
        assert item.id == "item-1"
        assert item.name == "report.pdf"
        assert item.size == 4096
        assert item.content_type == "application/pdf"
        assert item.download_url == "https://cdn.example.com/report.pdf"
        assert item.drive_id == "drive-1"
        assert item.path == "Invoices/"

    @pytest.mark.asyncio
    async def test_passes_through_when_download_url_suppressed(self):
        """Tenant policies strip @microsoft.graph.downloadUrl → field is None."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "item-2",
                    "name": "restricted.xlsx",
                    "size": 8192,
                    "file": {"mimeType": "application/vnd.openxmlformats"},
                },
            )

        client = _make_client(handler)
        item = await client.get_file_metadata("drive-1", "item-2")
        assert item.download_url is None
        assert item.drive_id == "drive-1"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": {"code": "accessDenied"}})

        client = _make_client(handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_file_metadata("drive-1", "missing")
