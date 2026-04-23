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
