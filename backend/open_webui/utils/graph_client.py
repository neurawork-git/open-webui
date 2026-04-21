"""Microsoft Graph API client for SharePoint folder operations."""

import httpx
import logging
from typing import Optional

from pydantic import BaseModel

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphFileItem(BaseModel):
    id: str
    name: str
    size: int
    content_type: Optional[str] = None
    download_url: Optional[str] = None


class GraphFolderListing(BaseModel):
    folder_name: str
    folder_path: str
    drive_id: str
    item_id: str
    files: list[GraphFileItem]
    skipped_folders: list[str]


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
        self, drive_id: str, item_id: str
    ) -> GraphFolderListing:
        """List files in a SharePoint/OneDrive folder. Non-recursive (v1)."""
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}"
        children_url = (
            f"{url}/children"
            f"?$select=id,name,size,file,folder,@microsoft.graph.downloadUrl"
            f"&$top=200"
        )

        client = self._client()
        try:
            meta_resp = await client.get(url, headers=self.headers)
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            files: list[GraphFileItem] = []
            skipped_folders: list[str] = []
            next_url: Optional[str] = children_url

            while next_url:
                resp = await client.get(next_url, headers=self.headers)
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("value", []):
                    if "folder" in item:
                        skipped_folders.append(item["name"])
                        continue
                    if "file" not in item:
                        continue
                    files.append(
                        GraphFileItem(
                            id=item["id"],
                            name=item["name"],
                            size=item.get("size", 0),
                            content_type=item.get("file", {}).get("mimeType"),
                            download_url=item.get(
                                "@microsoft.graph.downloadUrl"
                            ),
                        )
                    )

                next_url = data.get("@odata.nextLink")
        finally:
            if self._http_client is None:
                await client.aclose()

        return GraphFolderListing(
            folder_name=meta.get("name", ""),
            folder_path=meta.get("parentReference", {}).get("path", ""),
            drive_id=drive_id,
            item_id=item_id,
            files=files,
            skipped_folders=skipped_folders,
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
