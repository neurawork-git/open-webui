"""Farm-wide site discovery, its cache, and the web context every file call needs.

The defect these cover: discovery used to start at `/_api/v2.0/sites/root`, which returns
the root site collection and its direct subsites only -- 2 of 122 webs on the KHKI farm,
because `/wissen`, `/abteilungen` and `/teamseiten` are separate site collections and no
call enumerates those. And every file call went to `base_url` without a web prefix, which
answers HTTP 200 with an empty file list rather than an error.

A miniature farm stands in for the real one, with the same shape: several collections,
nesting past one level, and one branch the account may not see.
"""

import time

import httpx
import pytest

from open_webui.utils.sharepoint_onprem_client import (
    _DISCOVERY_CACHE,
    DISCOVERY_MAX_DEPTH,
    SharePointOnPremClient,
    encode_id,
    parse_site_roots,
)

BASE = 'https://portal.example.intern'

# path -> (title, [child paths]). '/projekte' is deliberately absent: it exists on the
# real farm but answers 401 for the service account, and must be skipped, not fatal.
FARM = {
    '/': ('Portal', ['/blog']),
    '/blog': ('Blog', []),
    '/wissen': ('Wissensportal', ['/wissen/HygieneInfo', '/wissen/Kliniken']),
    '/wissen/HygieneInfo': ('Hygiene', ['/wissen/HygieneInfo/tief']),
    '/wissen/HygieneInfo/tief': ('Ebene 3', []),
    '/wissen/Kliniken': ('Kliniken', []),
    '/abteilungen': ('Abteilungen', []),
}

ALL_ROOTS = '/,/wissen,/abteilungen,/projekte'


def _web_path(url: str) -> str:
    """Server-relative web path out of a request URL."""
    return url.split('/_api/')[0][len(BASE) :] or '/'


def _farm_handler(calls: list | None = None, fail: dict | None = None):
    """Mock transport for FARM. `fail` maps a web path to a status code."""
    fail = fail or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        path = _web_path(url)

        if path in fail:
            return httpx.Response(fail[path])
        if path not in FARM:
            return httpx.Response(404)

        title, children = FARM[path]
        if 'getsubwebsfilteredforcurrentuser' in url:
            return httpx.Response(
                200,
                json={
                    'value': [
                        {'Title': FARM[c][0], 'ServerRelativeUrl': c} for c in children
                    ]
                },
            )
        if '/_api/web?' in url:
            return httpx.Response(200, json={'Title': title, 'ServerRelativeUrl': path})
        return httpx.Response(404)

    return handler


def _client(handler, roots: str = ALL_ROOTS) -> SharePointOnPremClient:
    return SharePointOnPremClient(
        account='DOMAIN\\user',
        password='pw',
        base_url=BASE,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={'Accept': 'application/json'}
        ),
        site_roots=parse_site_roots(roots),
    )


class TestSiteRootParsing:
    def test_empty_means_the_root_only(self):
        """An instance nobody configured must behave exactly as it did before."""
        for raw in ('', '   ', None, ',,'):
            assert parse_site_roots(raw) == ['/']

    def test_the_root_survives_alongside_other_collections(self):
        """'/' trimmed to '' and dropped would lose the site everyone actually uses."""
        assert parse_site_roots('/,/wissen') == ['/', '/wissen']

    def test_shapes_are_normalised_and_deduplicated(self):
        assert parse_site_roots('wissen, /wissen/ ,/abteilungen') == [
            '/wissen',
            '/abteilungen',
        ]


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_every_configured_collection_is_walked(self):
        """The whole point: collections are not reachable from the root site."""
        webs = await _client(_farm_handler())._discover_webs()
        assert [w['path'] for w in webs] == [
            '/',
            '/abteilungen',
            '/blog',
            '/wissen',
            '/wissen/HygieneInfo',
            '/wissen/HygieneInfo/tief',
            '/wissen/Kliniken',
        ]

    @pytest.mark.asyncio
    async def test_recursion_goes_past_the_first_level(self):
        """`getsubwebsfilteredforcurrentuser` returns direct children only, so the client
        has to keep walking -- /abteilungen reaches level 5 on the real farm."""
        webs = await _client(_farm_handler())._discover_webs()
        depths = {w['path']: w['depth'] for w in webs}
        assert depths['/wissen'] == 0
        assert depths['/wissen/HygieneInfo'] == 1
        assert depths['/wissen/HygieneInfo/tief'] == 2

    @pytest.mark.asyncio
    async def test_a_forbidden_collection_is_skipped_not_fatal(self):
        """/projekte answers 401 for this account. The other four must still arrive."""
        webs = await _client(_farm_handler())._discover_webs()
        assert '/projekte' not in [w['path'] for w in webs]
        assert '/wissen' in [w['path'] for w in webs]

    @pytest.mark.asyncio
    async def test_one_unreadable_branch_does_not_lose_its_siblings(self):
        handler = _farm_handler(fail={'/wissen/Kliniken': 401})
        webs = await _client(handler)._discover_webs()
        paths = [w['path'] for w in webs]
        assert '/wissen/Kliniken' not in paths
        assert '/wissen/HygieneInfo' in paths

    @pytest.mark.asyncio
    async def test_verbose_odata_is_understood_too(self):
        """The farm decides the verbosity; {'d': {'results': []}} must not read as empty."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if 'getsubwebsfilteredforcurrentuser' in url:
                if _web_path(url) == '/':
                    return httpx.Response(
                        200,
                        json={
                            'd': {
                                'results': [
                                    {'Title': 'Blog', 'ServerRelativeUrl': '/blog'}
                                ]
                            }
                        },
                    )
                return httpx.Response(200, json={'d': {'results': []}})
            return httpx.Response(
                200, json={'Title': 'x', 'ServerRelativeUrl': _web_path(url)}
            )

        webs = await _client(handler, roots='/')._discover_webs()
        assert [w['path'] for w in webs] == ['/', '/blog']

    @pytest.mark.asyncio
    async def test_the_depth_limit_is_logged_when_it_bites(self, caplog):
        """A silent truncation reads as completeness -- which is the bug being fixed."""
        deep = {'/': ('Portal', ['/a'])}
        for i in range(1, DISCOVERY_MAX_DEPTH + 3):
            here = '/' + '/'.join('a' * 1 for _ in range(i))
            deep[here] = (f'level {i}', ['/' + here.strip('/') + '/a'])

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            path = _web_path(url)
            if 'getsubwebsfilteredforcurrentuser' in url:
                child = f'{path.rstrip("/")}/a'
                return httpx.Response(
                    200, json={'value': [{'Title': 'deeper', 'ServerRelativeUrl': child}]}
                )
            return httpx.Response(200, json={'Title': 'x', 'ServerRelativeUrl': path})

        with caplog.at_level('WARNING'):
            webs = await _client(handler, roots='/')._discover_webs()

        assert max(w['depth'] for w in webs) == DISCOVERY_MAX_DEPTH
        assert 'depth limit' in caplog.text


class TestDiscoveryCache:
    @pytest.mark.asyncio
    async def test_a_second_call_costs_no_requests(self):
        """~7 s of walking must not hang off every chat call."""
        calls: list[str] = []
        client = _client(_farm_handler(calls))

        await client._discover_webs()
        first = len(calls)
        assert first > 0

        await client._discover_webs()
        assert len(calls) == first

    @pytest.mark.asyncio
    async def test_another_account_gets_its_own_walk(self):
        """The listing is permission-trimmed, so one account's view is not another's."""
        calls: list[str] = []
        handler = _farm_handler(calls)
        await _client(handler)._discover_webs()
        first = len(calls)

        other = SharePointOnPremClient(
            account='DOMAIN\\someone-else',
            password='pw',
            base_url=BASE,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                headers={'Accept': 'application/json'},
            ),
            site_roots=parse_site_roots(ALL_ROOTS),
        )
        await other._discover_webs()
        assert len(calls) > first

    @pytest.mark.asyncio
    async def test_changing_the_entry_points_takes_effect_at_once(self):
        """The acceptance criterion for the admin setting: no restart, no TTL wait."""
        calls: list[str] = []
        handler = _farm_handler(calls)
        await _client(handler, roots='/')._discover_webs()

        webs = await _client(handler, roots='/,/wissen')._discover_webs()
        assert '/wissen' in [w['path'] for w in webs]

    @pytest.mark.asyncio
    async def test_an_expired_entry_is_walked_again(self):
        calls: list[str] = []
        client = _client(_farm_handler(calls))
        await client._discover_webs()
        first = len(calls)

        expires, webs = _DISCOVERY_CACHE[client._cache_key()]
        _DISCOVERY_CACHE[client._cache_key()] = (time.monotonic() - 1, webs)

        await client._discover_webs()
        assert len(calls) > first


class TestWebContext:
    @pytest.mark.asyncio
    async def test_the_longest_matching_web_wins(self):
        """A library belongs to its own web, not to the collection above it: the same
        folder answers 194 files from /wissen/HygieneInfo and 0 from /wissen."""
        client = _client(_farm_handler())
        assert (
            await client._web_for('/wissen/HygieneInfo/Hygiene Handbuch/a.pdf')
            == '/wissen/HygieneInfo'
        )

    @pytest.mark.asyncio
    async def test_a_shared_prefix_is_not_a_parent(self):
        """/wissenschaft must not resolve to /wissen."""
        client = _client(_farm_handler())
        assert await client._web_for('/wissenschaft/x.pdf') == ''

    @pytest.mark.asyncio
    async def test_the_root_web_yields_no_prefix(self):
        client = _client(_farm_handler())
        assert await client._web_for('/Dokumente/a.pdf') == ''

    @pytest.mark.asyncio
    async def test_an_unknown_path_triggers_discovery_rather_than_a_guess(self):
        calls: list[str] = []
        client = _client(_farm_handler(calls))
        _DISCOVERY_CACHE.clear()

        await client._web_for('/wissen/Kliniken/Dokumente/a.pdf')
        assert any('getsubwebsfilteredforcurrentuser' in c for c in calls)

    @pytest.mark.asyncio
    async def test_the_folder_url_carries_the_web_prefix(self):
        client = _client(_farm_handler())
        url = client._folder_url('/wissen/HygieneInfo/Handbuch', '/wissen/HygieneInfo')
        assert url.startswith('/wissen/HygieneInfo/_api/web/GetFolderByServerRelativeUrl')

    @pytest.mark.asyncio
    async def test_a_file_download_is_addressed_from_its_own_web(self):
        """The regression this exists for: /blog/SiteAssets returned 0 of 334 files from
        the root context."""
        seen: list[str] = []
        target = '/wissen/HygieneInfo/Handbuch/a.pdf'

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            seen.append(url)
            if '/_api/web?' in url or 'getsubwebs' in url:
                return _farm_handler()(request)
            return httpx.Response(200, content=b'%PDF')

        await _client(handler).download_file_by_id('d', encode_id(target))
        assert any(
            u.startswith(f'{BASE}/wissen/HygieneInfo/_api/web/GetFileByServerRelativeUrl')
            for u in seen
        )


class TestEmptySuspicion:
    """200 with nothing in it is a suspect, not a fact."""

    @staticmethod
    def _handler(item_count: int, files=(), folders=()):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if '/_api/web?' in url or 'getsubwebs' in url:
                return _farm_handler()(request)
            if 'GetList' in url:
                return httpx.Response(
                    200, json={'ItemCount': item_count, 'Title': 'Dokumente'}
                )
            return httpx.Response(
                200,
                json={
                    'Name': 'Dokumente',
                    'ServerRelativeUrl': '/wissen/Dokumente',
                    'Files': list(files),
                    'Folders': list(folders),
                },
            )

        return handler

    @pytest.mark.asyncio
    async def test_empty_listing_with_a_non_empty_list_is_an_error(self):
        client = _client(self._handler(item_count=194))
        with pytest.raises(httpx.HTTPStatusError, match='wrong site context'):
            await client.list_folder_children('d', encode_id('/wissen/Dokumente'))

    @pytest.mark.asyncio
    async def test_a_genuinely_empty_library_is_not_an_error(self):
        client = _client(self._handler(item_count=0))
        listing = await client.list_folder_children('d', encode_id('/wissen/Dokumente'))
        assert listing.files == [] and listing.folders == []

    @pytest.mark.asyncio
    async def test_folders_without_files_are_not_an_error(self):
        """A library holding only subfolders is perfectly ordinary."""
        client = _client(
            self._handler(
                item_count=5,
                folders=[{'Name': 'Unterordner', 'ServerRelativeUrl': '/wissen/x'}],
            )
        )
        listing = await client.list_folder_children('d', encode_id('/wissen/Dokumente'))
        assert [f.name for f in listing.folders] == ['Unterordner']

    @pytest.mark.asyncio
    async def test_a_plain_subfolder_without_a_list_is_not_an_error(self):
        """GetList only answers for a library root; an empty subfolder must stay empty."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if '/_api/web?' in url or 'getsubwebs' in url:
                return _farm_handler()(request)
            if 'GetList' in url:
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    'Name': 'leer',
                    'ServerRelativeUrl': '/wissen/Dokumente/leer',
                    'Files': [],
                    'Folders': [],
                },
            )

        listing = await _client(handler).list_folder_children(
            'd', encode_id('/wissen/Dokumente/leer')
        )
        assert listing.files == []


class TestNavigableListing:
    @pytest.mark.asyncio
    async def test_without_an_argument_only_the_top_two_levels_show(self):
        """122 webs flat is unusable for a language model."""
        result = await _client(_farm_handler()).list_webs()
        paths = {s['site_path'] for s in result['sites']}
        assert 'wissen' in paths and 'wissen/HygieneInfo' in paths
        assert 'wissen/HygieneInfo/tief' not in paths

    @pytest.mark.asyncio
    async def test_with_a_site_path_its_children_show(self):
        result = await _client(_farm_handler()).list_webs('wissen/HygieneInfo')
        assert [s['site_path'] for s in result['sites']] == ['wissen/HygieneInfo/tief']

    @pytest.mark.asyncio
    async def test_each_entry_carries_a_usable_site_path(self):
        """The value has to drop straight into browse()/list_libraries()."""
        result = await _client(_farm_handler()).list_webs('wissen')
        for entry in result['sites']:
            assert not entry['site_path'].startswith('/')
            assert entry['url'].startswith(BASE)


class TestSitePrefix:
    def test_a_nested_web_keeps_all_its_segments(self):
        """The old implementation returned '' for anything with a comma in it, so the
        picker showed the root site's libraries for every site."""
        client = _client(_farm_handler())
        assert client._site_prefix('wissen/HygieneInfo') == '/wissen/HygieneInfo'
        assert client._site_prefix('/wissen/') == '/wissen'
        assert client._site_prefix('') == ''
        assert client._site_prefix('/') == ''
