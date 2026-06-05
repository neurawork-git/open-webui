"""Microsoft Graph API client for SharePoint folder operations."""

import httpx
import logging
from typing import Optional

from pydantic import BaseModel

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

DEFAULT_MAX_FILES = 1000


class GraphFileItem(BaseModel):
    id: str
    name: str
    size: int
    content_type: Optional[str] = None
    download_url: Optional[str] = None
    # Relative path from the import root, "/" separated, e.g. "Invoices/2024/".
    # Empty string when the file sits at the root of the import.
    path: str = ""
    # Drive that owns the item — needed to fall back to /drives/{id}/items/{id}/content
    # when the tenant suppresses @microsoft.graph.downloadUrl from $select responses.
    drive_id: str = ""


class GraphFolderListing(BaseModel):
    folder_name: str
    folder_path: str
    drive_id: str
    item_id: str
    files: list[GraphFileItem]
    # True when the recursive walk hit `max_files` and stopped early.
    truncated: bool = False
    # Kept for backwards compatibility with earlier flat-only listing; always
    # empty in the recursive mode because subfolders are walked instead of skipped.
    skipped_folders: list[str] = []


class GraphDriveInfo(BaseModel):
    id: str
    name: str
    drive_type: str = ""
    root_item_id: str


class GraphSiteListing(BaseModel):
    site_id: str
    site_name: str
    site_url: str
    drives: list[GraphDriveInfo]
    # Flat file list spanning all drives; each file's `path` is prefixed with
    # its drive name (e.g. "Documents/Invoices/report.pdf") so the origin
    # remains visible in the flattened display filename.
    files: list[GraphFileItem]
    truncated: bool = False


class GraphSiteSummary(BaseModel):
    id: str
    name: str
    display_name: str
    web_url: str


class GraphDriveSummary(BaseModel):
    id: str
    name: str
    drive_type: str = ""
    root_item_id: str
    total_size: int = 0


class GraphChildItem(BaseModel):
    id: str
    name: str
    is_folder: bool
    size: int = 0
    child_count: int = 0
    content_type: Optional[str] = None


class GraphChildrenListing(BaseModel):
    parent_name: str
    parent_size: int = 0
    folders: list[GraphChildItem]
    files: list[GraphChildItem]
    next_link: Optional[str] = None


class GraphClient:
    """Calls Microsoft Graph API using a delegated user token from oauth_session."""

    def __init__(
        self,
        access_token: str,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.headers = {"Authorization": f"Bearer {access_token}"}
        self._http_client = http_client

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient()

    async def list_folder(
        self,
        drive_id: str,
        item_id: str,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> GraphFolderListing:
        """Recursively list all files in a SharePoint/OneDrive folder tree.

        Subfolders are walked depth-first. Each file's `path` records the
        relative path from the import root (e.g. "Invoices/2024/"). When the
        total file count would exceed `max_files`, the walk stops early and
        `truncated=True` is set on the result.
        """
        root_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"

        client = self._client()
        try:
            meta_resp = await client.get(root_url, headers=self.headers)
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            files: list[GraphFileItem] = []
            truncated = await self._walk(
                client, drive_id, item_id, "", files, max_files
            )
        finally:
            if self._http_client is None:
                await client.aclose()

        return GraphFolderListing(
            folder_name=meta.get("name", ""),
            folder_path=meta.get("parentReference", {}).get("path", ""),
            drive_id=drive_id,
            item_id=item_id,
            files=files,
            truncated=truncated,
        )

    async def _walk(
        self,
        client: httpx.AsyncClient,
        drive_id: str,
        folder_id: str,
        path: str,
        files: list[GraphFileItem],
        max_files: int,
    ) -> bool:
        """Depth-first walk appending files into the shared list.

        Returns True when `max_files` was reached and the walk stopped early.
        """
        subfolders: list[tuple[str, str]] = []

        next_url: Optional[str] = (
            f"{GRAPH_BASE}/drives/{drive_id}/items/{folder_id}/children"
            f"?$select=id,name,size,file,folder,@microsoft.graph.downloadUrl"
            f"&$top=200"
        )

        while next_url:
            resp = await client.get(next_url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("value", []):
                if "folder" in item:
                    subfolders.append((item["id"], f"{path}{item['name']}/"))
                    continue
                if "file" not in item:
                    continue
                if len(files) >= max_files:
                    return True
                files.append(
                    GraphFileItem(
                        id=item["id"],
                        name=item["name"],
                        size=item.get("size", 0),
                        content_type=item.get("file", {}).get("mimeType"),
                        download_url=item.get("@microsoft.graph.downloadUrl"),
                        path=path,
                        drive_id=drive_id,
                    )
                )

            next_url = data.get("@odata.nextLink")

        for sub_id, sub_path in subfolders:
            if len(files) >= max_files:
                return True
            if await self._walk(client, drive_id, sub_id, sub_path, files, max_files):
                return True

        return False

    async def list_site(
        self,
        site_id: str,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> GraphSiteListing:
        """Recursively list every file across every document library of a
        SharePoint site.

        Each file's `path` is prefixed with the drive name so downstream code
        can tell which library a file came from (e.g. a site with drives
        "Documents" and "Shared" produces paths like "Documents/" and
        "Shared/Invoices/"). Walks stop when `max_files` is reached.
        """
        client = self._client()
        try:
            site_resp = await client.get(
                f"{GRAPH_BASE}/sites/{site_id}", headers=self.headers
            )
            site_resp.raise_for_status()
            site = site_resp.json()

            drives_resp = await client.get(
                f"{GRAPH_BASE}/sites/{site_id}/drives", headers=self.headers
            )
            drives_resp.raise_for_status()
            drives_payload = drives_resp.json()

            drives: list[GraphDriveInfo] = []
            files: list[GraphFileItem] = []
            truncated = False

            for drive in drives_payload.get("value", []):
                drive_id = drive["id"]
                drive_name = drive.get("name") or "Documents"

                root_resp = await client.get(
                    f"{GRAPH_BASE}/drives/{drive_id}/root?$select=id",
                    headers=self.headers,
                )
                root_resp.raise_for_status()
                root_id = root_resp.json()["id"]

                drives.append(
                    GraphDriveInfo(
                        id=drive_id,
                        name=drive_name,
                        drive_type=drive.get("driveType", ""),
                        root_item_id=root_id,
                    )
                )

                truncated = await self._walk(
                    client, drive_id, root_id, f"{drive_name}/", files, max_files
                )
                if truncated:
                    break
        finally:
            if self._http_client is None:
                await client.aclose()

        return GraphSiteListing(
            site_id=site_id,
            site_name=site.get("displayName") or site.get("name", ""),
            site_url=site.get("webUrl", ""),
            drives=drives,
            files=files,
            truncated=truncated,
        )

    async def search_sites(self, query: str, top: int = 25) -> list[dict]:
        """Search SharePoint sites by title/URL.

        Returns a trimmed list of `{id, name, displayName, webUrl}` dicts
        suitable for a picker UI. Graph API: GET /sites?search={query}.
        """
        client = self._client()
        try:
            resp = await client.get(
                f"{GRAPH_BASE}/sites",
                headers=self.headers,
                params={"search": query, "$top": top},
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._http_client is None:
                await client.aclose()

        return [
            {
                "id": s["id"],
                "name": s.get("name", ""),
                "display_name": s.get("displayName", ""),
                "web_url": s.get("webUrl", ""),
            }
            for s in data.get("value", [])
        ]

    async def list_sites_paginated(
        self,
        query: str = "*",
        top: int = 100,
        next_link: Optional[str] = None,
    ) -> dict:
        """Paginated site listing.

        First call: pass `query` (default `*` for everything the caller can see)
        and `top`. Subsequent calls: pass `next_link` (the opaque
        `@odata.nextLink` from the previous response). Returns a dict with
        `sites` (list of GraphSiteSummary-shaped dicts) and `next_link`.
        """
        client = self._client()
        try:
            if next_link:
                resp = await client.get(next_link, headers=self.headers)
            else:
                resp = await client.get(
                    f"{GRAPH_BASE}/sites",
                    headers=self.headers,
                    params={"search": query, "$top": top},
                )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._http_client is None:
                await client.aclose()

        sites = [
            {
                "id": s["id"],
                "name": s.get("name", ""),
                "display_name": s.get("displayName", ""),
                "web_url": s.get("webUrl", ""),
            }
            for s in data.get("value", [])
        ]
        return {
            "sites": sites,
            "next_link": data.get("@odata.nextLink"),
        }

    async def list_site_drives_summary(self, site_id: str) -> dict:
        """List drives of a site with aggregate size for each.

        Returns `{site_name, site_url, drives: [GraphDriveSummary-dicts]}`.
        The drive size is read from `drive.quota.used` when available, falling
        back to the root item's aggregate `size` field.
        """
        client = self._client()
        try:
            site_resp = await client.get(
                f"{GRAPH_BASE}/sites/{site_id}", headers=self.headers
            )
            site_resp.raise_for_status()
            site = site_resp.json()

            drives_resp = await client.get(
                f"{GRAPH_BASE}/sites/{site_id}/drives", headers=self.headers
            )
            drives_resp.raise_for_status()
            drives_data = drives_resp.json()

            drives = []
            for drive in drives_data.get("value", []):
                drive_id = drive["id"]
                root_resp = await client.get(
                    f"{GRAPH_BASE}/drives/{drive_id}/root?$select=id,size",
                    headers=self.headers,
                )
                root_resp.raise_for_status()
                root = root_resp.json()
                quota_used = drive.get("quota", {}).get("used") or 0
                drives.append(
                    {
                        "id": drive_id,
                        "name": drive.get("name") or "Documents",
                        "drive_type": drive.get("driveType", ""),
                        "root_item_id": root["id"],
                        "total_size": int(quota_used or root.get("size", 0) or 0),
                    }
                )
        finally:
            if self._http_client is None:
                await client.aclose()

        return {
            "site_name": site.get("displayName") or site.get("name", ""),
            "site_url": site.get("webUrl", ""),
            "drives": drives,
        }

    async def list_folder_children(
        self,
        drive_id: str,
        item_id: str,
        top: int = 200,
        next_link: Optional[str] = None,
    ) -> GraphChildrenListing:
        """One-level listing of folder children with size metadata.

        Each returned folder carries `size` (aggregate recursive bytes from
        Graph's `driveItem.size`) and `child_count` (direct children). Files
        carry their own `size` and `content_type`. Paginated via the opaque
        `@odata.nextLink` passed back in the response.

        On the first page (when `next_link is None`), the parent item is also
        fetched so the caller can display a breadcrumb with the parent's name
        and total size.
        """
        client = self._client()
        try:
            parent_name = ""
            parent_size = 0
            if next_link is None:
                meta_resp = await client.get(
                    f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
                    "?$select=name,size",
                    headers=self.headers,
                )
                meta_resp.raise_for_status()
                meta = meta_resp.json()
                parent_name = meta.get("name", "")
                parent_size = int(meta.get("size", 0) or 0)

            if next_link:
                resp = await client.get(next_link, headers=self.headers)
            else:
                resp = await client.get(
                    f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/children",
                    headers=self.headers,
                    params={
                        "$select": "id,name,size,file,folder,@microsoft.graph.downloadUrl",
                        "$top": top,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._http_client is None:
                await client.aclose()

        folders: list[GraphChildItem] = []
        files: list[GraphChildItem] = []
        for item in data.get("value", []):
            if "folder" in item:
                folders.append(
                    GraphChildItem(
                        id=item["id"],
                        name=item.get("name", ""),
                        is_folder=True,
                        size=int(item.get("size", 0) or 0),
                        child_count=int(
                            item.get("folder", {}).get("childCount", 0) or 0
                        ),
                    )
                )
            elif "file" in item:
                files.append(
                    GraphChildItem(
                        id=item["id"],
                        name=item.get("name", ""),
                        is_folder=False,
                        size=int(item.get("size", 0) or 0),
                        content_type=item.get("file", {}).get("mimeType"),
                    )
                )

        return GraphChildrenListing(
            parent_name=parent_name,
            parent_size=parent_size,
            folders=folders,
            files=files,
            next_link=data.get("@odata.nextLink"),
        )

    async def get_file_metadata(
        self, drive_id: str, item_id: str, path: str = ""
    ) -> GraphFileItem:
        """Fetch current metadata for a single drive item.

        Used by the per-file import endpoint — between list and import the
        file may have been renamed, so we always re-resolve the name and
        downloadUrl from Graph instead of trusting frontend-echoed values.
        """
        url = (
            f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
            f"?$select=id,name,size,file,@microsoft.graph.downloadUrl"
        )
        client = self._client()
        try:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._http_client is None:
                await client.aclose()

        return GraphFileItem(
            id=data["id"],
            name=data.get("name", item_id),
            size=data.get("size", 0),
            content_type=data.get("file", {}).get("mimeType"),
            download_url=data.get("@microsoft.graph.downloadUrl"),
            path=path,
            drive_id=drive_id,
        )

    async def download_file(self, download_url: str) -> bytes:
        """Download file content from a Graph @microsoft.graph.downloadUrl."""
        client = self._client()
        try:
            resp = await client.get(download_url)
            resp.raise_for_status()
            return resp.content
        finally:
            if self._http_client is None:
                await client.aclose()

    async def download_file_by_id(self, drive_id: str, item_id: str) -> bytes:
        """Fallback download via /drives/{id}/items/{id}/content.

        Used when the tenant suppresses @microsoft.graph.downloadUrl in
        $select responses (e.g. Sensitivity-Label or DLP policy). The
        endpoint returns 302 to a short-lived pre-signed URL, which is
        why follow_redirects must be enabled on the request.
        """
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"
        if self._http_client is not None:
            resp = await self._http_client.get(
                url, headers=self.headers, follow_redirects=True
            )
            resp.raise_for_status()
            return resp.content
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.content
