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

Identifiers: outwards, `drive_id` and `item_id` are opaque `spo_<base64url>` tokens that
wrap a server-relative URL (see `encode_id`). They must not contain slashes, because they
travel as FastAPI *path* parameters. Underneath they are paths, so they break when an item
is renamed or moved -- a re-import then reports the file as missing.
`knowledge.meta.sharepoint_source.backend` records which backend issued them, so a
re-import cannot resolve them against the wrong system.

Other measured behaviour worth keeping in mind:
  /_api/web/currentUser                  200  identity, `i:0#.w|skkiel\\user`
  /_api/v2.0/sites/root, /sites/root/sites  200  root site + subsites
  /_api/web/lists                        200  all 27 libraries incl. ItemCount/BaseTemplate
  /_api/search/query                     500  no Search Service -> no full-text search
  /_api/web/webs, /_api/web/folders      401
"""

import base64
import logging
import re
import time
import urllib.parse
from html import unescape
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

# Document libraries. 101 is the classic document library; the picture templates
# (850/851/109) are technically browsable but are site furniture, not knowledge sources.
DOCUMENT_LIBRARY_TEMPLATE = 101

# 119 is the Site Pages library. It carries the portal's own prose -- 118 such libraries
# with 603 pages on the KHKI farm -- so it is browsable even though the .aspx files
# themselves are not worth downloading. `read_page` is the way to read one; the drive is
# reported with drive_type 'pages' so a caller can tell the two apart.
SITE_PAGES_TEMPLATE = 119
BROWSABLE_LIBRARY_TEMPLATES = {DOCUMENT_LIBRARY_TEMPLATE, SITE_PAGES_TEMPLATE}

# Calendars. Not a library at all, hence not browsable -- `list_events` reads them.
CALENDAR_TEMPLATE = 106

# Discovery bounds. Both are logged when they bite: a silent truncation reads as
# completeness, which is exactly the failure this whole feature exists to fix.
# Measured shape of the KHKI farm: 5 collections, depth 5, 122 webs.
DISCOVERY_MAX_DEPTH = 6
DISCOVERY_MAX_WEBS = 500

# A full walk costs ~7 s over an established connection, which must not hang off every
# chat call. Keyed per account because the result is permission-trimmed.
DISCOVERY_TTL_SECONDS = 900

# Module-level on purpose: `_onprem_backend` builds a fresh client -- and a fresh NTLM
# handshake -- for every request, so an instance-level cache would always be empty.
# {(base_url, account, roots): (expires_at_monotonic, webs)}
_DISCOVERY_CACHE: dict[tuple, tuple[float, list[dict]]] = {}

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


ID_PREFIX = 'spo_'


def encode_id(server_relative_url: str) -> str:
    """Server-relative URL -> opaque id without slashes.

    Necessary, not cosmetic: `drive_id` and `item_id` travel as FastAPI *path* parameters
    (`/sharepoint/drives/{drive_id}/items/{item_id}/children`), and a path parameter does
    not match `/`. Handing out `/Dokumente zur Befragung` makes that route unreachable.
    Percent-encoding is not a way out either -- many reverse proxies reject or normalise
    %2F before it ever reaches the app.

    The prefix also keeps the two worlds apart: a Graph id fed to this backend is
    recognisable as foreign instead of being sent to the farm as a path.
    """
    raw = base64.urlsafe_b64encode(server_relative_url.encode()).decode().rstrip('=')
    return f'{ID_PREFIX}{raw}'


def decode_id(value: str) -> str:
    """Opaque id -> server-relative URL. Raises on anything not issued by this backend."""
    if not value.startswith(ID_PREFIX):
        raise ValueError(
            f'Not an on-prem SharePoint id: {value[:40]!r}. This knowledge base was most '
            f'likely imported from Microsoft Graph.'
        )
    raw = value[len(ID_PREFIX) :]
    return base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)).decode()


def _quote_path(server_relative_url: str) -> str:
    """Escape a server-relative URL for use inside GetFolderByServerRelativeUrl('...').

    Single quotes must be doubled -- OData string literal rules -- or a file named
    "Mitarbeiter's.pdf" terminates the literal early and the farm answers 400.
    """
    return urllib.parse.quote(server_relative_url.replace("'", "''"), safe="/'()!$&+,;=:@ ")


def _odata_rows(payload: dict) -> list[dict]:
    """Rows out of a classic REST collection, whichever OData verbosity answered.

    `odata=nometadata` gives {'value': [...]}, `odata=verbose` {'d': {'results': [...]}}.
    The farm decides, not us -- JSON_HEADERS asks for neither explicitly.
    """
    if isinstance(payload.get('value'), list):
        return payload['value']
    results = (payload.get('d') or {}).get('results')
    return results if isinstance(results, list) else []


def _is_child_of(path: str, parent: str) -> bool:
    """Direct child in the web hierarchy, compared on segment boundaries.

    `/wissenschaft` must not read as a child of `/wissen`, and the farm is not
    case-sensitive about paths.
    """
    if parent == '/':
        return path != '/' and path.strip('/').count('/') == 0
    prefix = parent.casefold().rstrip('/') + '/'
    lowered = path.casefold()
    return lowered.startswith(prefix) and '/' not in lowered[len(prefix) :]


def _prefix_of(path: str, parent: str) -> bool:
    """`parent` is `path` itself or an ancestor of it, on segment boundaries."""
    if parent in ('', '/'):
        return True
    lowered = path.casefold()
    candidate = parent.casefold().rstrip('/')
    return lowered == candidate or lowered.startswith(candidate + '/')


def _html_to_text(html: str) -> str:
    """Page field HTML down to readable text. No new dependency for a handful of tags."""
    if not html:
        return ''
    text = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', html)
    text = re.sub(r'(?i)<br\s*/?>|</(p|div|li|tr|h[1-6])>', '\n', text)
    text = re.sub(r'(?s)<[^>]+>', ' ', text)
    text = unescape(text)
    text = re.sub(r'[ \t ]+', ' ', text)
    return re.sub(r'\n\s*\n\s*\n+', '\n\n', text).strip()


def parse_site_roots(raw: Optional[str]) -> list[str]:
    """Comma-separated entry points -> normalised server-relative paths.

    One function for both writers, so the admin panel stores exactly what discovery reads.
    Empty means '/', not "nothing": an instance that was never configured must behave as
    it did before this feature existed.
    """
    roots: list[str] = []
    for part in (raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        # '/' is a legitimate entry point next to '/wissen', so it must survive the
        # trailing-slash trim that turns '/wissen/' into '/wissen'.
        path = '/' + part.strip('/')
        if path not in roots:
            roots.append(path)
    return roots or ['/']


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
        site_roots: Optional[list[str]] = None,
    ):
        self.base_url = base_url.rstrip('/')
        self._account = account
        self._site_roots = list(site_roots) if site_roots else ['/']
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
    def _folder_url(server_relative_url: str, prefix: str = '') -> str:
        """`prefix` is the web that owns the folder -- see `_web_for` for why it matters."""
        return (
            f'{prefix}/_api/web/'
            f"GetFolderByServerRelativeUrl('{_quote_path(server_relative_url)}')"
            f'?$expand=Folders,Files'
        )

    # ------------------------------------------------------------------ identity

    async def whoami(self) -> dict:
        """Which AD account the farm sees. The proof that user rights apply rather than a
        service account's -- expects `i:0#.w|domain\\user`."""
        return await self._get_json('/_api/web/currentUser')

    # ------------------------------------------------------------------ sites

    def _cache_key(self) -> tuple:
        # The account, because the farm trims every listing to what that identity may see.
        # The roots, so an edit in the admin panel takes effect on the next call instead
        # of after the TTL -- that is the acceptance criterion for the setting.
        return (self.base_url, self._account, tuple(self._site_roots))

    async def _discover_webs(self, force: bool = False) -> list[dict]:
        """Every web reachable from the configured entry points, breadth-first.

        Why not just ask the farm for its sites: `/_api/v2.0/sites` answers
        400 `Cannot enumerate sites`, the search-backed variants 500, and the crawler
        interfaces (`SiteData.asmx`, `Webs.asmx`) 401. Measured 2026-08-04 -- there is no
        call that lists site collections, which is why they are configured.

        Within a collection, `/_api/web/webs` is 401 but
        `getsubwebsfilteredforcurrentuser` is 200 and permission-trimmed, so it is both
        the working *and* the correct source. Note that Microsoft documents that method as
        "SharePoint Online only"; it is nevertheless 200 on this farm (20 calls in 1.07 s).
        Do not "fix" this back to `web/webs` on the strength of the documentation.

        Returns dicts of {path, title, depth, root} sorted by path. A branch that answers
        401/404 is skipped, not fatal: one unreadable department must not cost the farm.
        """
        key = self._cache_key()
        if not force:
            cached = _DISCOVERY_CACHE.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]

        webs: list[dict] = []
        seen: set[str] = set()
        truncated = False

        for root in self._site_roots:
            if await self._walk_webs(root, webs, seen):
                truncated = True
                break

        if truncated:
            log.warning(
                'Discovery: stopped at the %s-web limit -- the result is incomplete',
                DISCOVERY_MAX_WEBS,
            )

        webs.sort(key=lambda w: w['path'])
        _DISCOVERY_CACHE[key] = (time.monotonic() + DISCOVERY_TTL_SECONDS, webs)
        return webs

    async def _walk_webs(self, root: str, webs: list[dict], seen: set[str]) -> bool:
        """Breadth-first from one entry point. True if the web limit stopped the walk."""
        queue: list[tuple[str, int]] = [(root, 0)]
        while queue:
            path, depth = queue.pop(0)
            normalised = '/' + path.strip('/')
            if normalised.casefold() in seen:
                continue
            if len(webs) >= DISCOVERY_MAX_WEBS:
                return True

            try:
                node = await self._read_web(normalised)
            except httpx.HTTPStatusError as e:
                # 401 arrives here as 404 via _request when the identity still resolves;
                # either way the branch is simply not ours to see.
                log.info('Discovery: skipping %s (%s)', normalised, e.response.status_code)
                continue

            seen.add(normalised.casefold())
            webs.append({**node, 'depth': depth, 'root': root})

            if depth >= DISCOVERY_MAX_DEPTH:
                log.warning(
                    'Discovery: depth limit %s reached at %s -- subsites below it are not listed',
                    DISCOVERY_MAX_DEPTH,
                    normalised,
                )
                continue

            for child in await self._child_webs(node['path']):
                queue.append((child, depth + 1))

        return False

    async def _read_web(self, path: str) -> dict:
        """Title and canonical server-relative URL of one web."""
        prefix = '' if path == '/' else path
        data = await self._get_json(f'{prefix}/_api/web?$select=Title,ServerRelativeUrl')
        server_relative = data.get('ServerRelativeUrl') or path
        return {
            'path': '/' + server_relative.strip('/'),
            'title': data.get('Title') or '',
        }

    async def _child_webs(self, path: str) -> list[str]:
        """Immediate subsites of one web. The method does not recurse -- callers must."""
        prefix = '' if path == '/' else path
        try:
            data = await self._get_json(
                f'{prefix}/_api/web/getsubwebsfilteredforcurrentuser'
                f'(nWebTemplateFilter=-1,nConfigurationFilter=-1)'
            )
        except httpx.HTTPStatusError as e:
            log.info('Discovery: no subsites for %s (%s)', path, e.response.status_code)
            return []

        out = []
        for entry in _odata_rows(data):
            url = entry.get('ServerRelativeUrl') or entry.get('Url') or ''
            if url:
                out.append('/' + url.strip('/'))
        return out

    def _site_summary(self, web: dict) -> dict:
        path = web.get('path') or '/'
        # The id IS the server-relative path. Previously it was the v2.0 GUID, which
        # `_site_prefix` could not turn into a prefix -- so every site's library listing
        # silently answered with the *root* site's libraries.
        return {
            'id': path,
            'name': path,
            'display_name': web.get('title') or ('Portal' if path == '/' else path),
            'web_url': f'{self.base_url}{"" if path == "/" else path}',
        }

    async def search_sites(self, query: str, top: int = 25) -> list[dict]:
        """Name filter, not full-text search: this farm's Search Service answers 500, so
        `/_api/search/query` is unusable. Callers get sites whose name contains `query`."""
        needle = (query or '').strip().casefold()
        out = []
        for web in await self._discover_webs():
            summary = self._site_summary(web)
            haystack = f'{summary["name"]} {summary["display_name"]}'.casefold()
            if not needle or needle == '*' or needle in haystack:
                out.append(summary)
        return out[:top]

    async def list_sites_paginated(
        self, query: str = '*', top: int = 100, next_link: Optional[str] = None
    ) -> dict:
        # An on-prem site list is small and arrives in one response; there is no
        # continuation token to hand back. Deliberately flat even at 122 entries -- the
        # picker filters client-side, and `list_webs` is what serves navigation.
        if next_link:
            return {'sites': [], 'next_link': None}
        return {'sites': await self.search_sites(query, top=top), 'next_link': None}

    async def list_webs(self, site_path: Optional[str] = None) -> dict:
        """Navigable view of the farm. On-prem only, not part of SharePointBackend.

        122 sites in one flat list is unusable for a language model. Without an argument
        this returns the entry points and their first level; with one, the children of
        exactly that web. Every entry carries the `site_path` the other calls expect.
        """
        webs = await self._discover_webs()
        if site_path is None:
            # depth 0 are the entry points themselves, depth 1 their first level.
            visible = [w for w in webs if w['depth'] <= 1]
            parent = None
        else:
            parent = '/' + site_path.strip('/')
            visible = [w for w in webs if _is_child_of(w['path'], parent)]

        return {
            'parent': parent,
            'sites': [
                {
                    'site_path': w['path'].lstrip('/'),
                    'title': w['title'],
                    'depth': w['depth'],
                    'url': f'{self.base_url}{"" if w["path"] == "/" else w["path"]}',
                }
                for w in visible
            ],
        }

    def _site_prefix(self, site_id: str) -> str:
        """`/_api` prefix for a web. The root web has no prefix.

        `site_id` is a server-relative path, possibly several segments deep
        (`wissen/HygieneInfo`). It used to also carry v2.0 GUID ids, which were silently
        mapped to no prefix at all -- see `_site_summary`.
        """
        path = (site_id or '').strip('/')
        return f'/{path}' if path else ''

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
            template = lst.get('BaseTemplate')
            if lst.get('Hidden') or template not in BROWSABLE_LIBRARY_TEMPLATES:
                continue
            root_url = (lst.get('RootFolder') or {}).get('ServerRelativeUrl')
            if not root_url:
                continue
            drives.append(
                {
                    'id': encode_id(root_url),
                    'name': lst.get('Title') or root_url,
                    # 'pages' marks a Site Pages library. Browsable, but its .aspx files
                    # are markup wrappers -- `read_page` is what reads their content.
                    'drive_type': (
                        'documentLibrary'
                        if template == DOCUMENT_LIBRARY_TEMPLATE
                        else 'pages'
                    ),
                    'root_item_id': encode_id(root_url),
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

    async def _web_for(self, server_relative_url: str) -> str:
        """Longest known web path that is a prefix of this URL.

        This is the whole point of discovery for file operations. Addressing a folder from
        the wrong web answers **HTTP 200 with an empty Files collection** rather than an
        error -- measured on `/wissen/HygieneInfo/Hygiene Handbuch` (194 files from its own
        web, 0 from `/wissen`) and on `/blog/SiteAssets` (334 from `/blog`, 0 from the root
        of its own site collection). A caller checking only the status code reads that as
        an empty folder.

        Unknown path: discovery runs rather than the root context being guessed.
        """
        target = '/' + (server_relative_url or '').strip('/')
        best = ''
        for web in await self._discover_webs():
            path = web['path']
            if _prefix_of(target, path) and len(path) > len(best):
                best = path

        if not best:
            # Force one rediscovery -- a library added under a new web is the common case.
            for web in await self._discover_webs(force=True):
                path = web['path']
                if _prefix_of(target, path) and len(path) > len(best):
                    best = path

        if not best:
            log.warning(
                'No known web for %s -- falling back to the root context, which may '
                'return an empty listing instead of an error',
                target,
            )
        return '' if best in ('', '/') else best

    async def _read_folder(self, server_relative_url: str, prefix: Optional[str] = None) -> dict:
        if prefix is None:
            prefix = await self._web_for(server_relative_url)
        return await self._get_json(self._folder_url(server_relative_url, prefix))

    async def _assert_not_context_blind(
        self, data: dict, server_relative_url: str, prefix: str
    ) -> None:
        """A listing that came back completely empty is a suspect, not a fact.

        `ItemCount` counts folders as well as files, so it cannot be reconciled exactly --
        but "the list says N>0 and we can see neither a file nor a folder" is the exact
        signature of the wrong web context (3.4 of the requirements). Reporting it as an
        empty folder is the silent falsehood this guard exists to prevent.
        """
        if (data.get('Files') or []) or (data.get('Folders') or []):
            return

        try:
            meta = await self._get_json(
                f'{prefix}/_api/web/GetList('
                f"'{_quote_path(server_relative_url)}')?$select=ItemCount,Title"
            )
        except httpx.HTTPStatusError:
            # Not a library root (an ordinary subfolder), so there is nothing to compare
            # against. An empty subfolder is perfectly normal.
            return

        item_count = int(meta.get('ItemCount') or 0)
        if item_count <= 0:
            return

        raise httpx.HTTPStatusError(
            f'{server_relative_url!r} returned no files or folders, but the list reports '
            f'{item_count} items. This is the signature of a wrong site context '
            f'(context used: {prefix or "/"}). Re-run discovery or pass the site_path of '
            f'the web that actually owns this library.',
            request=httpx.Request('GET', self._url(f'{prefix}/_api/web')),
            response=httpx.Response(409),
        )

    async def _walk(
        self,
        folder_url: str,
        path: str,
        files: list[GraphFileItem],
        drive_id: str,
        max_files: int,
        prefix: Optional[str] = None,
    ) -> bool:
        """Depth-first walk appending files into the shared list. Mirrors
        GraphClient._walk, including the early-stop semantics.

        `prefix` is resolved once by the caller: a walk stays inside one library, hence
        inside one web, so re-deriving it per folder would only cost requests.
        """
        if prefix is None:
            prefix = await self._web_for(folder_url)
        data = await self._read_folder(folder_url, prefix)

        for item in data.get('Files') or []:
            if len(files) >= max_files:
                return True
            name = item.get('Name', '')
            files.append(
                GraphFileItem(
                    id=encode_id(item.get('ServerRelativeUrl', '')),
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
                sub.get('ServerRelativeUrl', ''),
                f'{path}{name}/',
                files,
                drive_id,
                max_files,
                prefix,
            ):
                return True

        return False

    async def list_folder(
        self, drive_id: str, item_id: str, max_files: int = DEFAULT_MAX_FILES
    ) -> GraphFolderListing:
        root = decode_id(item_id or drive_id)
        prefix = await self._web_for(root)
        meta = await self._read_folder(root, prefix)
        await self._assert_not_context_blind(meta, root, prefix)

        files: list[GraphFileItem] = []
        truncated = await self._walk(root, '', files, drive_id, max_files, prefix)

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
        target = decode_id(item_id or drive_id)
        prefix = await self._web_for(target)
        data = await self._read_folder(target, prefix)
        await self._assert_not_context_blind(data, target, prefix)

        folders: list[GraphChildItem] = []
        for sub in data.get('Folders') or []:
            name = sub.get('Name', '')
            if name in SYSTEM_FOLDERS:
                continue
            folders.append(
                GraphChildItem(
                    id=encode_id(sub.get('ServerRelativeUrl', '')),
                    name=name,
                    is_folder=True,
                    # ponytail: 0 = unknown, not empty. GetFolderByServerRelativeUrl
                    # returns no aggregate size for subfolders (Graph's driveItem.size
                    # has no on-prem equivalent), and summing it would cost one request
                    # per folder on every listing. The picker hides a 0 instead of
                    # printing "0 B", and the import size check is unaffected -- it
                    # walks the tree and sums real `Length` values. Upgrade path if a
                    # number is ever needed up front: Folder/StorageMetrics, one extra
                    # $expand per folder.
                    size=0,
                    child_count=int(sub.get('ItemCount') or 0),
                )
            )

        files: list[GraphChildItem] = []
        for item in data.get('Files') or []:
            name = item.get('Name', '')
            files.append(
                GraphChildItem(
                    id=encode_id(item.get('ServerRelativeUrl', '')),
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
        site_prefix = self._site_prefix(site_id)

        drives: list[GraphDriveInfo] = []
        files: list[GraphFileItem] = []
        truncated = False

        for drive in summary['drives']:
            # Browsable is not the same as importable. A Site Pages library holds .aspx
            # wrappers whose text lives in list fields, so importing the files verbatim
            # would fill a knowledge base with markup. They stay visible in the picker and
            # readable through `read_page`; a whole-site import skips them.
            if drive.get('drive_type') == 'pages':
                continue
            drives.append(
                GraphDriveInfo(
                    id=drive['id'],
                    name=drive['name'],
                    drive_type=drive.get('drive_type', ''),
                    root_item_id=drive['root_item_id'],
                )
            )
            try:
                # Every library of a site lives in that site's web, so the context is
                # resolved once per site rather than once per library.
                truncated = await self._walk(
                    decode_id(drive['id']),
                    f'{drive["name"]}/',
                    files,
                    drive['id'],
                    max_files,
                    site_prefix,
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

    # ------------------------------------------- pages, events, links (on-prem only)
    #
    # None of these are part of the SharePointBackend protocol. That protocol is a
    # contract GraphClient has to honour too, and a cloud tenant has neither this farm's
    # broken search nor its page layout. Callers reach them through the on-prem client
    # directly and should guard with hasattr.

    async def _lists_by_template(self, prefix: str, template: int) -> list[dict]:
        """Lists of one BaseTemplate, addressed by GUID afterwards.

        Deliberately not `getbytitle('Site Pages')`: this farm is German, so that library
        is called "Websiteseiten". BaseTemplate is language-independent.
        """
        payload = await self._get_json(
            f'{prefix}/_api/web/lists'
            f'?$select=Id,Title,BaseTemplate,ItemCount,Hidden'
            f'&$filter=BaseTemplate eq {template}'
        )
        return [row for row in _odata_rows(payload) if not row.get('Hidden')]

    async def _page_fields(
        self, prefix: str, list_id: str, leaf: str, site_path: str
    ) -> dict:
        """Title plus whichever content field the page actually has.

        Two requests rather than one $select naming both fields: a classic SP2016 site may
        not have CanvasContent1 at all, and one unknown field in $select fails the *entire*
        query with 400 InvalidClientQueryException -- asking for both at once would lose
        the wiki text too.
        """
        base = f"{prefix}/_api/web/lists(guid'{list_id}')/items"
        filter_clause = f"$filter=FileLeafRef eq '{leaf.replace(chr(39), chr(39) * 2)}'"

        fields: dict[str, str] = {}
        for field in ('WikiField', 'CanvasContent1'):
            try:
                payload = await self._get_json(
                    f'{base}?$select=Title,FileLeafRef,{field}&{filter_clause}&$top=1'
                )
            except httpx.HTTPStatusError as e:
                # Detected by status, not by message text -- the farm localises it.
                if e.response.status_code in (400, 404):
                    log.info('read_page: %s unavailable on %s', field, site_path or '/')
                    continue
                raise
            rows = _odata_rows(payload)
            if rows:
                fields.setdefault('title', rows[0].get('Title') or leaf)
                value = rows[0].get(field)
                if value:
                    fields[field] = value
        return fields

    async def read_page(self, site_path: str, page: str) -> dict:
        """Text of one portal page.

        The content is in list fields, not in the .aspx file: `WikiField` on classic wiki
        pages, `CanvasContent1` on modern ones. Downloading the file itself yields markup
        with no prose in it.
        """
        prefix = self._site_prefix(site_path)
        leaf = (page or '').strip('/').rsplit('/', 1)[-1]
        if not leaf:
            raise ValueError('read_page needs a page file name, e.g. Homepage.aspx')

        lists = await self._lists_by_template(prefix, SITE_PAGES_TEMPLATE)
        if not lists:
            raise httpx.HTTPStatusError(
                f'No Site Pages library on {site_path or "/"}.',
                request=httpx.Request('GET', self._url(f'{prefix}/_api/web/lists')),
                response=httpx.Response(404),
            )

        for entry in lists:
            list_id = entry.get('Id')
            if not list_id:
                continue

            fields = await self._page_fields(prefix, list_id, leaf, site_path)
            if 'title' not in fields:
                continue

            text = _html_to_text(fields.get('WikiField') or fields.get('CanvasContent1') or '')
            note = None
            if not text:
                # Classic web parts (a calendar rollup, say) keep their configuration in
                # the web part database. Neither field carries them and no REST call
                # reveals which list a page displays -- so say so instead of returning
                # an empty string that reads like an empty page.
                note = (
                    'This page carries no text in WikiField or CanvasContent1. Its content '
                    'most likely comes from web parts, whose configuration is not readable '
                    'over the REST API -- read the underlying list directly.'
                )

            return {
                'site_path': (site_path or '').strip('/'),
                'page': leaf,
                'title': fields.get('title') or leaf,
                'text': text,
                'note': note,
            }

        raise httpx.HTTPStatusError(
            f'Page {leaf!r} not found on {site_path or "/"}.',
            request=httpx.Request('GET', self._url(f'{prefix}/_api/web')),
            response=httpx.Response(404),
        )

    async def list_events(
        self, site_path: str = '', from_date: str = '', top: int = 20
    ) -> dict:
        """Upcoming entries from the calendars of one web.

        Unfiltered this would return events back to 2009 -- 1537 of them in the root
        calendar alone. `from_date` is an ISO date; the default is today.
        """
        prefix = self._site_prefix(site_path)
        since = (from_date or '').strip() or time.strftime('%Y-%m-%d', time.gmtime())
        # Classic SP REST speaks OData v2/v3: the literal has to be datetime'...'.
        # A bare ISO string or datetimeoffset'...' is rejected here.
        literal = f"datetime'{since}T00:00:00Z'"

        calendars = await self._lists_by_template(prefix, CALENDAR_TEMPLATE)
        events: list[dict] = []
        for entry in calendars:
            list_id = entry.get('Id')
            if not list_id:
                continue
            try:
                payload = await self._get_json(
                    f"{prefix}/_api/web/lists(guid'{list_id}')/items"
                    f'?$select=Title,EventDate,EndDate,Location,fAllDayEvent,fRecurrence'
                    f'&$filter=EndDate ge {literal}'
                    f'&$orderby=EventDate asc&$top={int(top)}'
                )
            except httpx.HTTPStatusError as e:
                log.info(
                    'list_events: calendar %r unreadable (%s)',
                    entry.get('Title'),
                    e.response.status_code,
                )
                continue

            for row in _odata_rows(payload):
                events.append(
                    {
                        'calendar': entry.get('Title') or '',
                        'title': row.get('Title') or '',
                        'start': row.get('EventDate'),
                        'end': row.get('EndDate'),
                        'location': row.get('Location') or '',
                        'all_day': bool(row.get('fAllDayEvent')),
                        # A recurring event answers as its series head only. REST cannot
                        # expand occurrences -- DateTimeRangesOverlap is documented as
                        # unsupported in $filter -- so the head is flagged rather than
                        # silently standing in for every date it implies.
                        'recurring': bool(row.get('fRecurrence')),
                    }
                )

        events.sort(key=lambda e: (e['start'] or ''))
        return {
            'site_path': (site_path or '').strip('/'),
            'from': since,
            'calendars': [c.get('Title') or '' for c in calendars],
            'events': events[:top],
        }

    async def resolve_url(self, url: str) -> dict:
        """A shared portal link -> site_path, library and path.

        The everyday entry point is a link someone pasted, not a site path anyone knows.
        """
        raw = (url or '').strip()
        if not raw:
            raise ValueError('resolve_url needs a URL')

        parsed = urllib.parse.urlparse(raw)
        if parsed.scheme and f'{parsed.scheme}://{parsed.netloc}'.rstrip('/') != self.base_url:
            raise ValueError(
                f'{raw!r} does not belong to this farm ({self.base_url}).'
            )
        server_relative = '/' + urllib.parse.unquote(parsed.path or raw).strip('/')

        web = await self._web_for(server_relative)
        remainder = server_relative[len(web) :].strip('/') if web else server_relative.strip('/')

        library = ''
        path = ''
        if remainder:
            library, _, path = remainder.partition('/')

        # Report the library's display title where one exists -- 'SitePages' is the URL
        # segment, "Websiteseiten" is what the user sees.
        library_title = library
        if library:
            try:
                summary = await self.list_site_drives_summary(web.strip('/'))
                for drive in summary['drives']:
                    root = decode_id(drive['root_item_id']).rstrip('/')
                    if root.casefold() == f'{web}/{library}'.casefold():
                        library_title = drive['name']
                        break
            except httpx.HTTPStatusError as e:
                log.info('resolve_url: no library list for %s (%s)', web, e.response.status_code)

        return {
            'site_path': web.strip('/'),
            'library': library_title,
            'library_path': library,
            'path': path,
            'server_relative_url': server_relative,
        }

    # ------------------------------------------------------------------ files

    async def get_file_metadata(
        self, drive_id: str, item_id: str, path: str = ''
    ) -> GraphFileItem:
        path_url = decode_id(item_id)
        prefix = await self._web_for(path_url)
        data = await self._get_json(
            f'{prefix}/_api/web/'
            f"GetFileByServerRelativeUrl('{_quote_path(path_url)}')"
            f'?$select=Name,Length,ServerRelativeUrl,UniqueId'
        )
        name = data.get('Name', '')
        return GraphFileItem(
            id=encode_id(data.get('ServerRelativeUrl') or path_url),
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
        target = decode_id(item_id)
        prefix = await self._web_for(target)
        return await self._get_bytes(
            f'{prefix}/_api/web/'
            f"GetFileByServerRelativeUrl('{_quote_path(target)}')/$value"
        )
