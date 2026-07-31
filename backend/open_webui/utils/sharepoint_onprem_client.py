"""SharePoint Server SE client over NTLM, shaped like GraphClient (fork-local).

Why this exists: the KHKI farm offers NTLM only -- no Negotiate, no OIDC zone, no Entra.
A delegated Graph token cannot be obtained, so per-user access needs the user's own AD
credential and an NTLM handshake.

Which API this speaks, and why that is not the obvious one
----------------------------------------------------------
The farm does serve the Graph-compatible `/_api/v2.0/` dialect, and an earlier measurement
recorded "9 of 11 endpoints 200". Measured again on 2026-07-31 against libraries that
actually contain something, the picture is different:

    library                        BaseTemplate  ItemCount  v2.0 /children  classic /Files
    Abgabebibliothek                        101          0             200               0
    Dokumente                               101          0             200               0
    Dokumente der Websitesammlung           101          0             200               0
    Dokumente zur Befragung                 101          3             400               3
    Bilder                                  851         23             400              17
    Bilder der Websitesammlung              851         11             400               4
    Seiten                                  850          1             400               1
    Video News                              109          1             400               1

`/_api/v2.0/drives/{id}/root/children` answers 200 exactly while a library is EMPTY and
400 `invalidRequest` as soon as it holds items -- for every addressing form (`/root/children`,
`/root:/:/children`, `/items/root/children`). The earlier "it works" reading came from
empty libraries. So the v2.0 dialect cannot enumerate content on this farm.

Therefore folders and files go through the classic `_api/web` route, which returns real
data for every library above. `/_api/v2.0/sites/...` is kept only for site enumeration,
where it is proven.

Identifiers: `drive_id` and `item_id` carry SERVER-RELATIVE URLs (e.g.
`/Dokumente zur Befragung`), not opaque Graph ids. They are stable while nothing is
renamed or moved; `knowledge.meta.sharepoint_source.backend` records which backend issued
them so a re-import cannot resolve them against the wrong system.

Other measured behaviour worth keeping in mind:
  /_api/web/currentUser                  200  identity, `i:0#.w|skkiel\\user`
  /_api/v2.0/sites/root, /sites/root/sites  200  root site + subsites
  /_api/web/lists                        200  all 27 libraries incl. ItemCount/BaseTemplate
  /_api/search/query                     500  no Search Service -> no full-text search
  /_api/web/webs, /_api/web/folders      401
"""

import base64
import logging
import urllib.parse
from typing import Optional

import httpx
import spnego
from open_webui.utils.graph_client import (
    DEFAULT_MAX_FILES,
    GraphChildItem,
    GraphChildrenListing,
    GraphDriveInfo,
    GraphFileItem,
    GraphFolderListing,
    GraphSiteListing,
)

log = logging.getLogger(__name__)

# `odata=nometadata` makes the v2.0 endpoints answer 400 invalidRequest, and the classic
# route is happy without it. Measured, not assumed.
JSON_HEADERS = {'Accept': 'application/json'}

# Document libraries. 101 is the classic document library; the picture/page templates
# (850/851/109) are technically browsable but are site furniture, not knowledge sources.
DOCUMENT_LIBRARY_TEMPLATE = 101

# SharePoint's own plumbing inside a library. Importing these would drag form templates
# and thumbnail caches into a knowledge base.
SYSTEM_FOLDERS = {'Forms', '_t', '_w', '_catalogs', '_private', '_vti_pvt'}

MIME_BY_EXTENSION = {
    'pdf': 'application/pdf',
    'txt': 'text/plain',
    'md': 'text/markdown',
    'csv': 'text/csv',
    'json': 'application/json',
    'xml': 'application/xml',
    'html': 'text/html',
    'htm': 'text/html',
    'doc': 'application/msword',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'xls': 'application/vnd.ms-excel',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'ppt': 'application/vnd.ms-powerpoint',
    'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'png': 'image/png',
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'gif': 'image/gif',
}


def _mime_for(name: str) -> Optional[str]:
    return MIME_BY_EXTENSION.get(name.rsplit('.', 1)[-1].lower()) if '.' in name else None


def _quote_path(server_relative_url: str) -> str:
    """Escape a server-relative URL for use inside GetFolderByServerRelativeUrl('...').

    Single quotes must be doubled -- OData string literal rules -- or a file named
    "Mitarbeiter's.pdf" terminates the literal early and the farm answers 400.
    """
    return urllib.parse.quote(server_relative_url.replace("'", "''"), safe="/'()!$&+,;=:@ ")


def _parse_ntlm_challenge(www_authenticate: str) -> Optional[bytes]:
    for part in www_authenticate.split(','):
        part = part.strip()
        if part.upper().startswith('NTLM ') and len(part) > 5:
            try:
                return base64.b64decode(part[5:])
            except Exception:
                return None
    return None


class NtlmAuth(httpx.Auth):
    """Three-leg NTLM handshake as an httpx auth flow.

    Implemented against pyspnego directly rather than pulling in httpx-ntlm, whose last
    release predates httpx 0.28 by two years. The surface here is small enough to audit.

    `auth_flow` is a sync generator on purpose -- httpx's `Auth.async_auth_flow` drives it
    with next()/send() and performs all network I/O itself at the `yield`, so nothing
    blocks the event loop. `spnego.step()` is local cryptography only.
    """

    requires_response_body = False

    def __init__(self, account: str, password: str):
        self._account = account
        self._password = password

    def auth_flow(self, request: httpx.Request):
        response = yield request
        if response.status_code != 401:
            return

        offered = response.headers.get('www-authenticate', '')
        if 'ntlm' not in offered.lower():
            # Farm did not offer NTLM -- retrying would only burn a logon attempt.
            return
        challenge_offered = _parse_ntlm_challenge(offered)

        ctx = spnego.client(
            self._account,
            self._password,
            protocol='ntlm',
            hostname=request.url.host,
        )
        negotiate = ctx.step()
        request.headers['Authorization'] = 'NTLM ' + base64.b64encode(negotiate).decode()
        response = yield request

        challenge = _parse_ntlm_challenge(response.headers.get('www-authenticate', ''))
        if challenge is None:
            challenge = challenge_offered
        if challenge is None:
            return

        authenticate = ctx.step(challenge)
        request.headers['Authorization'] = 'NTLM ' + base64.b64encode(authenticate).decode()
        yield request


class SharePointOnPremClient:
    """Satisfies utils.sharepoint_backend.SharePointBackend against SharePoint SE."""

    def __init__(
        self,
        account: str,
        password: str,
        base_url: str,
        http_client: Optional[httpx.AsyncClient] = None,
        verify: bool = True,
    ):
        self.base_url = base_url.rstrip('/')
        self._account = account
        self._owns_client = http_client is None
        if http_client is not None:
            self._http_client = http_client
        else:
            # NTLM authenticates a TCP connection, not a request. Capping the pool at one
            # connection is what keeps the three handshake legs on the same socket; httpx
            # gives no such guarantee on its own. HTTP/2 multiplexing is off for the same
            # reason.
            self._http_client = httpx.AsyncClient(
                http2=False,
                verify=verify,
                timeout=60.0,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
                auth=NtlmAuth(account, password),
                headers=JSON_HEADERS,
                follow_redirects=True,
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    # ------------------------------------------------------------------ HTTP

    def _url(self, path: str) -> str:
        return f'{self.base_url}{path if path.startswith("/") else "/" + path}'

    async def _request(self, path_or_url: str) -> httpx.Response:
        """GET with one important correction on 401.

        This farm answers 401 for a path that does not exist, not just for a rejected
        logon -- `GetFolderByServerRelativeUrl('root')` returns 401, measured 2026-07-31.
        Passing that through unchanged would make the caller delete a perfectly good
        stored credential and force a needless re-login.

        So a 401 is re-checked against `/_api/web/currentUser` on the same, already
        authenticated connection. If the identity still resolves, the credential is fine
        and the real problem is the path: it surfaces as 404. Only a 401 that survives
        that check is reported as a credential rejection. No password is re-submitted
        either way, so this cannot cost a logon attempt.
        """
        url = path_or_url if path_or_url.startswith('http') else self._url(path_or_url)
        resp = await self._http_client.get(url)

        if resp.status_code == 401 and not url.endswith('/_api/web/currentUser'):
            probe = await self._http_client.get(self._url('/_api/web/currentUser'))
            if probe.status_code == 200:
                log.info('401 on %s but the identity still resolves -- treating as not found', url)
                raise httpx.HTTPStatusError(
                    'Resource not found or not permitted for this user',
                    request=resp.request,
                    response=httpx.Response(404, request=resp.request),
                )

        resp.raise_for_status()
        return resp

    async def _get_json(self, path_or_url: str) -> dict:
        return (await self._request(path_or_url)).json()

    async def _get_bytes(self, path_or_url: str) -> bytes:
        return (await self._request(path_or_url)).content

    @staticmethod
    def _folder_url(server_relative_url: str) -> str:
        return (
            f"/_api/web/GetFolderByServerRelativeUrl('{_quote_path(server_relative_url)}')"
            f'?$expand=Folders,Files'
        )

    # ------------------------------------------------------------------ identity

    async def whoami(self) -> dict:
        """Which AD account the farm sees. The proof that user rights apply rather than a
        service account's -- expects `i:0#.w|domain\\user`."""
        return await self._get_json('/_api/web/currentUser')

    # ------------------------------------------------------------------ sites

    async def _all_sites(self) -> list[dict]:
        sites: list[dict] = []
        root = await self._get_json('/_api/v2.0/sites/root')
        sites.append(root)
        try:
            subs = await self._get_json('/_api/v2.0/sites/root/sites')
            sites.extend(subs.get('value') or [])
        except httpx.HTTPStatusError as e:
            log.info('Subsite listing unavailable (%s)', e.response.status_code)
        return sites

    @staticmethod
    def _site_summary(site: dict) -> dict:
        name = site.get('name') or ''
        return {
            'id': site.get('id', ''),
            'name': name,
            # The root site reports an empty name; showing the host is friendlier than
            # an empty row in the picker.
            'display_name': site.get('displayName') or name or 'Portal',
            'web_url': site.get('webUrl', ''),
        }

    async def search_sites(self, query: str, top: int = 25) -> list[dict]:
        """Name filter, not full-text search: this farm's Search Service answers 500, so
        `/_api/search/query` is unusable. Callers get sites whose name contains `query`."""
        needle = (query or '').strip().casefold()
        out = []
        for site in await self._all_sites():
            summary = self._site_summary(site)
            haystack = f'{summary["name"]} {summary["display_name"]}'.casefold()
            if not needle or needle == '*' or needle in haystack:
                out.append(summary)
        return out[:top]

    async def list_sites_paginated(
        self, query: str = '*', top: int = 100, next_link: Optional[str] = None
    ) -> dict:
        # An on-prem site list is small and arrives in one response; there is no
        # continuation token to hand back.
        if next_link:
            return {'sites': [], 'next_link': None}
        return {'sites': await self.search_sites(query, top=top), 'next_link': None}

    def _site_prefix(self, site_id: str) -> str:
        """`/_api` prefix for a subsite. The root site has no prefix.

        Site ids from the v2.0 dialect look like `host,guid,guid`; the picker also passes
        plain subsite paths such as `blog`.
        """
        if not site_id or ',' in site_id:
            return ''
        return '/' + site_id.strip('/')

    async def list_site_drives_summary(self, site_id: str) -> dict:
        """Document libraries of a site, from the classic list API.

        `/_api/v2.0/.../drives` is not used here: it reported 8 of the 27 libraries and
        gave every one of them `quota.used = 0`, so both the set and the sizes were wrong.
        """
        prefix = self._site_prefix(site_id)
        web = await self._get_json(f'{prefix}/_api/web?$select=Title,Url')
        payload = await self._get_json(
            f'{prefix}/_api/web/lists'
            f'?$select=Title,BaseTemplate,ItemCount,Hidden,RootFolder/ServerRelativeUrl'
            f'&$expand=RootFolder'
        )

        drives = []
        for lst in payload.get('value') or []:
            if lst.get('Hidden') or lst.get('BaseTemplate') != DOCUMENT_LIBRARY_TEMPLATE:
                continue
            root_url = (lst.get('RootFolder') or {}).get('ServerRelativeUrl')
            if not root_url:
                continue
            drives.append(
                {
                    'id': root_url,
                    'name': lst.get('Title') or root_url,
                    'drive_type': 'documentLibrary',
                    'root_item_id': root_url,
                    # The farm reports no per-library byte total, and summing every file
                    # would mean walking every library just to draw a picker. ItemCount
                    # is what it does give us.
                    'total_size': 0,
                    'item_count': int(lst.get('ItemCount') or 0),
                }
            )

        return {
            'site_name': web.get('Title') or '',
            'site_url': web.get('Url') or '',
            'drives': drives,
        }

    # ------------------------------------------------------------------ folders

    async def _read_folder(self, server_relative_url: str) -> dict:
        return await self._get_json(self._folder_url(server_relative_url))

    async def _walk(
        self,
        folder_url: str,
        path: str,
        files: list[GraphFileItem],
        drive_id: str,
        max_files: int,
    ) -> bool:
        """Depth-first walk appending files into the shared list. Mirrors
        GraphClient._walk, including the early-stop semantics."""
        data = await self._read_folder(folder_url)

        for item in data.get('Files') or []:
            if len(files) >= max_files:
                return True
            name = item.get('Name', '')
            files.append(
                GraphFileItem(
                    id=item.get('ServerRelativeUrl', ''),
                    name=name,
                    size=int(item.get('Length') or 0),
                    content_type=_mime_for(name),
                    # No pre-signed URL on-prem; the importer falls back to
                    # download_file_by_id, which is the path that carries NTLM.
                    download_url=None,
                    path=path,
                    drive_id=drive_id,
                )
            )

        for sub in data.get('Folders') or []:
            name = sub.get('Name', '')
            if name in SYSTEM_FOLDERS:
                continue
            if len(files) >= max_files:
                return True
            if await self._walk(
                sub.get('ServerRelativeUrl', ''), f'{path}{name}/', files, drive_id, max_files
            ):
                return True

        return False

    async def list_folder(
        self, drive_id: str, item_id: str, max_files: int = DEFAULT_MAX_FILES
    ) -> GraphFolderListing:
        root = item_id or drive_id
        meta = await self._read_folder(root)

        files: list[GraphFileItem] = []
        truncated = await self._walk(root, '', files, drive_id, max_files)

        return GraphFolderListing(
            folder_name=meta.get('Name', ''),
            folder_path=meta.get('ServerRelativeUrl', ''),
            drive_id=drive_id,
            item_id=item_id,
            files=files,
            truncated=truncated,
        )

    async def list_folder_children(
        self,
        drive_id: str,
        item_id: str,
        top: int = 200,
        next_link: Optional[str] = None,
    ) -> GraphChildrenListing:
        # The classic Folders/Files collections return in one response; there is no
        # continuation token, so next_link is always None going out.
        data = await self._read_folder(item_id or drive_id)

        folders: list[GraphChildItem] = []
        for sub in data.get('Folders') or []:
            name = sub.get('Name', '')
            if name in SYSTEM_FOLDERS:
                continue
            folders.append(
                GraphChildItem(
                    id=sub.get('ServerRelativeUrl', ''),
                    name=name,
                    is_folder=True,
                    size=0,
                    child_count=int(sub.get('ItemCount') or 0),
                )
            )

        files: list[GraphChildItem] = []
        for item in data.get('Files') or []:
            name = item.get('Name', '')
            files.append(
                GraphChildItem(
                    id=item.get('ServerRelativeUrl', ''),
                    name=name,
                    is_folder=False,
                    size=int(item.get('Length') or 0),
                    content_type=_mime_for(name),
                )
            )

        return GraphChildrenListing(
            parent_name=data.get('Name', ''),
            parent_size=0,
            folders=folders,
            files=files,
            next_link=None,
        )

    async def list_site(
        self, site_id: str, max_files: int = DEFAULT_MAX_FILES
    ) -> GraphSiteListing:
        summary = await self.list_site_drives_summary(site_id)

        drives: list[GraphDriveInfo] = []
        files: list[GraphFileItem] = []
        truncated = False

        for drive in summary['drives']:
            drives.append(
                GraphDriveInfo(
                    id=drive['id'],
                    name=drive['name'],
                    drive_type=drive.get('drive_type', ''),
                    root_item_id=drive['root_item_id'],
                )
            )
            try:
                truncated = await self._walk(
                    drive['id'], f'{drive["name"]}/', files, drive['id'], max_files
                )
            except httpx.HTTPStatusError as e:
                # One unreadable library must not abort the whole site import.
                log.warning(
                    'Skipping library %r during site import (%s)',
                    drive['name'],
                    e.response.status_code,
                )
                continue
            if truncated:
                break

        return GraphSiteListing(
            site_id=site_id,
            site_name=summary['site_name'],
            site_url=summary['site_url'],
            drives=drives,
            files=files,
            truncated=truncated,
        )

    # ------------------------------------------------------------------ files

    async def get_file_metadata(
        self, drive_id: str, item_id: str, path: str = ''
    ) -> GraphFileItem:
        data = await self._get_json(
            f"/_api/web/GetFileByServerRelativeUrl('{_quote_path(item_id)}')"
            f'?$select=Name,Length,ServerRelativeUrl,UniqueId'
        )
        name = data.get('Name', '')
        return GraphFileItem(
            id=data.get('ServerRelativeUrl', item_id),
            name=name,
            size=int(data.get('Length') or 0),
            content_type=_mime_for(name),
            download_url=None,
            path=path,
            drive_id=drive_id,
        )

    async def download_file(self, download_url: str) -> bytes:
        # On-prem items carry no pre-signed URL, so this is only reached if a caller kept
        # one from somewhere. It still goes through the authenticated client.
        return await self._get_bytes(download_url)

    async def download_file_by_id(self, drive_id: str, item_id: str) -> bytes:
        return await self._get_bytes(
            f"/_api/web/GetFileByServerRelativeUrl('{_quote_path(item_id)}')/$value"
        )
