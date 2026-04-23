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
