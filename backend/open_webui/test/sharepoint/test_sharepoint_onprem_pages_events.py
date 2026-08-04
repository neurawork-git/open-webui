"""Reading what is not a document: page text, calendar entries, and shared links.

36 % of this farm's 20,180 list items live outside document libraries -- page content in
list fields, 2,569 entries across 17 calendars -- and the browse/find/read calls filter
hard on BaseTemplate 101, so none of it was reachable.

These three are on-prem only and deliberately not part of SharePointBackend: the protocol
binds GraphClient too, and a cloud tenant has neither this page layout nor this farm's
broken search.
"""

import urllib.parse

import httpx
import pytest

from open_webui.utils.sharepoint_onprem_client import (
    SharePointOnPremClient,
    encode_id,
    parse_site_roots,
)

BASE = 'https://portal.example.intern'
PAGES_LIST = '11111111-1111-1111-1111-111111111111'
CALENDAR_LIST = '22222222-2222-2222-2222-222222222222'

WEBS = ['/', '/wissen', '/wissen/allgemein', '/wissen/Veranstalt']


def _client(handler) -> SharePointOnPremClient:
    from open_webui.utils.sharepoint_onprem_client import (
        _DISCOVERY_CACHE,
        DISCOVERY_TTL_SECONDS,
    )
    import time

    client = SharePointOnPremClient(
        account='DOMAIN\\user',
        password='pw',
        base_url=BASE,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={'Accept': 'application/json'}
        ),
        site_roots=parse_site_roots('/,/wissen'),
    )
    _DISCOVERY_CACHE[client._cache_key()] = (
        time.monotonic() + DISCOVERY_TTL_SECONDS,
        [{'path': p, 'title': p, 'depth': 0, 'root': '/'} for p in WEBS],
    )
    return client


def _pages_handler(rows_by_field: dict, missing: tuple = ()):
    """`missing` names fields the farm does not have -- a classic SP2016 site has no
    CanvasContent1, and one unknown field in $select fails the whole query with 400."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = urllib.parse.unquote(str(request.url))
        if '/_api/web/lists?' in url and 'BaseTemplate eq 119' in url:
            return httpx.Response(
                200,
                json={'value': [{'Id': PAGES_LIST, 'Title': 'Websiteseiten', 'Hidden': False}]},
            )
        if f"lists(guid'{PAGES_LIST}')/items" in url:
            for field in missing:
                if field in url:
                    return httpx.Response(
                        400,
                        json={
                            'error': {
                                'code': '-1, Microsoft.SharePoint.Client.'
                                'InvalidClientQueryException',
                                'message': {'lang': 'de-DE', 'value': 'Spalte fehlt'},
                            }
                        },
                    )
            for field, value in rows_by_field.items():
                if field in url:
                    return httpx.Response(
                        200,
                        json={
                            'value': [
                                {
                                    'Title': 'Startseite',
                                    'FileLeafRef': 'Homepage.aspx',
                                    field: value,
                                }
                            ]
                        },
                    )
            return httpx.Response(200, json={'value': []})
        return httpx.Response(404)

    return handler


class TestReadPage:
    @pytest.mark.asyncio
    async def test_a_classic_wiki_page_reads_from_wikifield(self):
        handler = _pages_handler({'WikiField': '<p>Hygiene <b>Regeln</b></p>'})
        result = await _client(handler).read_page('wissen/allgemein', 'Homepage.aspx')
        assert result['text'] == 'Hygiene Regeln'
        assert result['site_path'] == 'wissen/allgemein'

    @pytest.mark.asyncio
    async def test_a_modern_page_reads_from_canvascontent1(self):
        handler = _pages_handler({'CanvasContent1': '<div>Moderner Text</div>'})
        result = await _client(handler).read_page('wissen/allgemein', 'Homepage_Modern.aspx')
        assert result['text'] == 'Moderner Text'

    @pytest.mark.asyncio
    async def test_a_missing_canvascontent1_does_not_lose_the_wiki_text(self):
        """The reason the two fields are fetched separately: one $select naming both
        fails entirely on a site that has no CanvasContent1."""
        handler = _pages_handler(
            {'WikiField': '<p>Klassisch</p>'}, missing=('CanvasContent1',)
        )
        result = await _client(handler).read_page('wissen/allgemein', 'Homepage.aspx')
        assert result['text'] == 'Klassisch'

    @pytest.mark.asyncio
    async def test_a_web_part_page_says_so_instead_of_returning_nothing(self):
        """Web part configuration lives in the web part database and is not readable over
        REST. An empty string would read as an empty page."""
        handler = _pages_handler({'WikiField': ''})
        result = await _client(handler).read_page('wissen/Veranstalt', 'Homepage_Modern.aspx')
        assert result['text'] == ''
        assert 'web parts' in result['note']

    @pytest.mark.asyncio
    async def test_the_page_library_is_found_by_template_not_by_title(self):
        """This farm is German: the library is called "Websiteseiten", so
        getbytitle('Site Pages') would 404."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(urllib.parse.unquote(str(request.url)))
            return _pages_handler({'WikiField': '<p>x</p>'})(request)

        await _client(handler).read_page('wissen/allgemein', 'Homepage.aspx')
        assert any('BaseTemplate eq 119' in u for u in seen)
        assert not any('getbytitle' in u.lower() for u in seen)

    @pytest.mark.asyncio
    async def test_a_site_without_a_page_library_is_a_clean_404(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if '/_api/web/lists?' in str(request.url):
                return httpx.Response(200, json={'value': []})
            return httpx.Response(404)

        with pytest.raises(httpx.HTTPStatusError, match='No Site Pages library'):
            await _client(handler).read_page('wissen', 'Homepage.aspx')


def _calendar_handler(rows: list, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = urllib.parse.unquote(str(request.url))
        if seen is not None:
            seen.append(url)
        if '/_api/web/lists?' in url and 'BaseTemplate eq 106' in url:
            return httpx.Response(
                200,
                json={
                    'value': [
                        {'Id': CALENDAR_LIST, 'Title': 'Hygienefortbildungen', 'Hidden': False}
                    ]
                },
            )
        if f"lists(guid'{CALENDAR_LIST}')/items" in url:
            return httpx.Response(200, json={'value': rows})
        return httpx.Response(404)

    return handler


class TestListEvents:
    @pytest.mark.asyncio
    async def test_the_date_filter_uses_the_odata_v2_literal(self):
        """Classic SP REST is OData v2/v3. A bare ISO string or datetimeoffset'...' is
        rejected -- this is the single most common mistake at this endpoint."""
        seen: list[str] = []
        await _client(_calendar_handler([], seen)).list_events(
            'wissen/HygieneInfo', from_date='2026-08-04'
        )
        item_calls = [u for u in seen if '/items' in u]
        assert item_calls
        assert "datetime'2026-08-04T00:00:00Z'" in item_calls[0]

    @pytest.mark.asyncio
    async def test_events_come_back_with_their_calendar_and_times(self):
        rows = [
            {
                'Title': 'Händehygiene',
                'EventDate': '2026-08-10T08:00:00Z',
                'EndDate': '2026-08-10T09:00:00Z',
                'Location': 'Raum 1',
                'fAllDayEvent': False,
                'fRecurrence': False,
            }
        ]
        result = await _client(_calendar_handler(rows)).list_events('wissen/HygieneInfo')
        assert result['events'][0]['title'] == 'Händehygiene'
        assert result['events'][0]['calendar'] == 'Hygienefortbildungen'
        assert result['events'][0]['location'] == 'Raum 1'

    @pytest.mark.asyncio
    async def test_a_recurring_event_is_flagged_rather_than_silently_standing_in(self):
        """$filter returns the series head only -- DateTimeRangesOverlap is documented as
        unsupported -- so the gap is made visible instead of hidden."""
        rows = [
            {
                'Title': 'Wöchentliche Visite',
                'EventDate': '2026-08-10T08:00:00Z',
                'EndDate': '2026-08-10T09:00:00Z',
                'fRecurrence': True,
            }
        ]
        result = await _client(_calendar_handler(rows)).list_events('wissen/Pflege')
        assert result['events'][0]['recurring'] is True

    @pytest.mark.asyncio
    async def test_a_top_limit_is_always_sent(self):
        """1,537 events reaching back to 2009 sit in the root calendar alone."""
        seen: list[str] = []
        await _client(_calendar_handler([], seen)).list_events('', top=5)
        assert any('$top=5' in u for u in seen if '/items' in u)

    @pytest.mark.asyncio
    async def test_one_unreadable_calendar_does_not_sink_the_call(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = urllib.parse.unquote(str(request.url))
            if 'BaseTemplate eq 106' in url:
                return httpx.Response(
                    200,
                    json={
                        'value': [
                            {'Id': CALENDAR_LIST, 'Title': 'Gesperrt', 'Hidden': False}
                        ]
                    },
                )
            return httpx.Response(403)

        result = await _client(handler).list_events('wissen')
        assert result['events'] == []
        assert result['calendars'] == ['Gesperrt']


class TestResolveUrl:
    @staticmethod
    def _handler(request: httpx.Request) -> httpx.Response:
        url = urllib.parse.unquote(str(request.url))
        if '/_api/web?' in url:
            return httpx.Response(200, json={'Title': 'x', 'ServerRelativeUrl': '/'})
        if '/_api/web/lists' in url:
            return httpx.Response(
                200,
                json={
                    'value': [
                        {
                            'Title': 'Websiteseiten',
                            'BaseTemplate': 119,
                            'ItemCount': 12,
                            'Hidden': False,
                            'RootFolder': {
                                'ServerRelativeUrl': '/wissen/allgemein/SitePages'
                            },
                        }
                    ]
                },
            )
        return httpx.Response(404)

    @pytest.mark.asyncio
    async def test_a_shared_page_link_resolves_to_site_library_and_file(self):
        """The everyday entry point is a pasted link, not a site path anyone knows."""
        result = await _client(self._handler).resolve_url(
            f'{BASE}/wissen/allgemein/SitePages/Homepage_Modern.aspx'
        )
        assert result['site_path'] == 'wissen/allgemein'
        assert result['library'] == 'Websiteseiten'
        assert result['path'] == 'Homepage_Modern.aspx'

    @pytest.mark.asyncio
    async def test_percent_encoding_is_undone(self):
        result = await _client(self._handler).resolve_url(
            f'{BASE}/wissen/allgemein/SitePages/Mein%20Dokument.pdf'
        )
        assert result['path'] == 'Mein Dokument.pdf'

    @pytest.mark.asyncio
    async def test_a_link_to_another_host_is_refused(self):
        """Silently treating a foreign URL as a farm path would send someone else's path
        to this farm."""
        with pytest.raises(ValueError, match='does not belong to this farm'):
            await _client(self._handler).resolve_url('https://example.com/wissen/x.pdf')

    @pytest.mark.asyncio
    async def test_a_bare_site_url_resolves_to_the_site_alone(self):
        result = await _client(self._handler).resolve_url(f'{BASE}/wissen/allgemein')
        assert result['site_path'] == 'wissen/allgemein'
        assert result['library'] == '' and result['path'] == ''


class TestPageLibrariesAreBrowsableButNotImportable:
    @staticmethod
    def _handler(request: httpx.Request) -> httpx.Response:
        url = urllib.parse.unquote(str(request.url))
        if '/_api/web?' in url:
            return httpx.Response(200, json={'Title': 'Wissen', 'Url': f'{BASE}/wissen'})
        if '/_api/web/lists' in url:
            return httpx.Response(
                200,
                json={
                    'value': [
                        {
                            'Title': 'Dokumente',
                            'BaseTemplate': 101,
                            'ItemCount': 3,
                            'Hidden': False,
                            'RootFolder': {'ServerRelativeUrl': '/wissen/Dokumente'},
                        },
                        {
                            'Title': 'Websiteseiten',
                            'BaseTemplate': 119,
                            'ItemCount': 7,
                            'Hidden': False,
                            'RootFolder': {'ServerRelativeUrl': '/wissen/SitePages'},
                        },
                        {
                            'Title': 'Bilder',
                            'BaseTemplate': 851,
                            'ItemCount': 9,
                            'Hidden': False,
                            'RootFolder': {'ServerRelativeUrl': '/wissen/Bilder'},
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                'Name': 'Dokumente',
                'ServerRelativeUrl': '/wissen/Dokumente',
                'Files': [
                    {
                        'Name': 'a.pdf',
                        'Length': '10',
                        'ServerRelativeUrl': '/wissen/Dokumente/a.pdf',
                    }
                ],
                'Folders': [],
            },
        )

    @pytest.mark.asyncio
    async def test_a_page_library_shows_up_in_the_picker(self):
        summary = await _client(self._handler).list_site_drives_summary('wissen')
        by_name = {d['name']: d for d in summary['drives']}
        assert by_name['Websiteseiten']['drive_type'] == 'pages'
        assert by_name['Dokumente']['drive_type'] == 'documentLibrary'
        assert 'Bilder' not in by_name  # 851 is site furniture, still excluded

    @pytest.mark.asyncio
    async def test_a_whole_site_import_skips_it(self):
        """Its .aspx files are markup wrappers; importing them verbatim would fill a
        knowledge base with layout instead of prose."""
        listing = await _client(self._handler).list_site('wissen')
        assert [d.name for d in listing.drives] == ['Dokumente']
