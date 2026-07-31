"""Unit tests for SharePointOnPremClient -- SharePoint SE over NTLM.

Same shape as test_graph_client.py: an httpx.MockTransport stands in for the farm, so the
three-leg NTLM handshake and the v2.0 endpoint mapping are exercised without a network.
"""

import base64

import httpx
import pytest

from open_webui.utils.graph_client import GraphClient
from open_webui.utils.sharepoint_backend import SharePointBackend
from open_webui.utils.sharepoint_onprem_client import (
    NtlmAuth,
    SharePointOnPremClient,
    _parse_ntlm_challenge,
    decode_id,
    encode_id,
)

BASE = 'https://portal.example.intern'
DRIVE = 'drive-1'


def _make_client(handler, with_auth: bool = False) -> SharePointOnPremClient:
    """Client with a mocked transport. NTLM is off by default so endpoint tests are not
    obscured by handshake bookkeeping."""
    transport = httpx.MockTransport(handler)
    kwargs = {'transport': transport, 'headers': {'Accept': 'application/json'}}
    if with_auth:
        kwargs['auth'] = NtlmAuth('DOMAIN\\user', 'pw')
    http_client = httpx.AsyncClient(**kwargs)
    return SharePointOnPremClient(
        account='DOMAIN\\user', password='pw', base_url=BASE, http_client=http_client
    )


LIB_PATH = '/Dokumente zur Befragung'
# Ids handed to the client are always the opaque form -- that is what the routes carry.
LIB = encode_id(LIB_PATH)


def _file(name: str, folder: str = LIB_PATH, size: int = 1024):
    """A file as the classic `_api/web` route returns it."""
    return {
        'Name': name,
        'Length': str(size),
        'ServerRelativeUrl': f'{folder}/{name}',
        'UniqueId': f'uid-{name}',
    }


def _folder(name: str, parent: str = LIB_PATH, item_count: int = 2):
    return {
        'Name': name,
        'ServerRelativeUrl': f'{parent}/{name}',
        'ItemCount': item_count,
    }


def _folder_payload(name: str, path: str, folders=None, files=None):
    return {
        'Name': name,
        'ServerRelativeUrl': path,
        'Folders': folders or [],
        'Files': files or [],
    }


# ---------------------------------------------------------------------------
# NTLM handshake
# ---------------------------------------------------------------------------


class TestNtlmHandshake:
    def test_parse_challenge_from_header(self):
        token = base64.b64encode(b'NTLMSSP\x00\x02').decode()
        assert _parse_ntlm_challenge(f'NTLM {token}') == b'NTLMSSP\x00\x02'

    def test_parse_challenge_among_other_schemes(self):
        token = base64.b64encode(b'chal').decode()
        assert _parse_ntlm_challenge(f'Negotiate, NTLM {token}') == b'chal'

    def test_no_ntlm_offered_returns_none(self):
        assert _parse_ntlm_challenge('Basic realm="x"') is None

    @pytest.mark.asyncio
    async def test_three_leg_handshake_completes(self, monkeypatch):
        """401 -> Type1 -> 401+Type2 -> Type3 -> 200, all on one client.

        The spnego context is stubbed on purpose. What is under test is the leg
        sequencing and the base64 header handling in NtlmAuth -- not NTLM cryptography,
        which belongs to pyspnego and cannot be driven with synthetic tokens (SSPI on
        Windows rejects them outright).
        """
        received_challenge = {}

        class _FakeContext:
            def step(self, token=None):
                if token is None:
                    return b'TYPE1-NEGOTIATE'
                received_challenge['value'] = token
                return b'TYPE3-AUTHENTICATE'

        monkeypatch.setattr(
            'open_webui.utils.sharepoint_onprem_client.spnego.client',
            lambda *a, **kw: _FakeContext(),
        )

        seen: list[str] = []
        challenge_bytes = b'NTLMSSP\x00\x02FAKE-CHALLENGE'

        def handler(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get('authorization')
            seen.append(auth or '<none>')
            if auth is None:
                return httpx.Response(401, headers={'WWW-Authenticate': 'NTLM'}, json={})
            if len(seen) == 2:
                challenge = base64.b64encode(challenge_bytes).decode()
                return httpx.Response(
                    401, headers={'WWW-Authenticate': f'NTLM {challenge}'}, json={}
                )
            return httpx.Response(200, json={'LoginName': 'i:0#.w|domain\\user'})

        client = _make_client(handler, with_auth=True)
        result = await client.whoami()

        assert result['LoginName'] == 'i:0#.w|domain\\user'
        assert len(seen) == 3
        assert seen[0] == '<none>'
        assert seen[1] == 'NTLM ' + base64.b64encode(b'TYPE1-NEGOTIATE').decode()
        assert seen[2] == 'NTLM ' + base64.b64encode(b'TYPE3-AUTHENTICATE').decode()
        # The server's Type-2 challenge must reach the context undecorated.
        assert received_challenge['value'] == challenge_bytes

    @pytest.mark.asyncio
    async def test_farm_without_ntlm_does_not_retry(self):
        """Retrying against a farm that never offered NTLM would only burn logon
        attempts against the account lockout counter."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(401, headers={'WWW-Authenticate': 'Basic'}, json={})

        client = _make_client(handler, with_auth=True)
        with pytest.raises(httpx.HTTPStatusError):
            await client.whoami()

        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Endpoint mapping (classic _api/web route)
#
# Not the v2.0 dialect: measured 2026-07-31, /_api/v2.0/drives/{id}/root/children answers
# 200 only while a library is EMPTY, and 400 invalidRequest as soon as it holds items.
# ---------------------------------------------------------------------------


class TestIdentifiers:
    """Found by an end-to-end run, not by unit tests: `drive_id` and `item_id` travel as
    FastAPI *path* parameters, and a path parameter does not match `/`. Handing out raw
    server-relative URLs made `/sharepoint/drives/{drive_id}/items/{item_id}/children`
    unreachable on-prem."""

    def test_ids_never_contain_a_slash(self):
        for path in ['/Freigegebene Dokumente', '/a/b/c.pdf', "/Mitarbeiter's/x.pdf"]:
            assert '/' not in encode_id(path), path

    def test_roundtrip_survives_spaces_umlauts_and_quotes(self):
        for path in [
            '/Dokumente zur Befragung/FAQ.pdf',
            '/Prüfung/Änderung & Co.pdf',
            "/Mitarbeiter's.pdf",
        ]:
            assert decode_id(encode_id(path)) == path

    def test_a_graph_id_is_rejected_before_any_request(self):
        """A Graph id must not be sent to the farm as a path."""
        with pytest.raises(ValueError, match='Not an on-prem SharePoint id'):
            decode_id('01PDQZT256Y2GOVW7725BZO354PWSELRRZ')


class TestEndpoints:
    @pytest.mark.asyncio
    async def test_accept_header_has_no_odata_suffix(self):
        """`odata=nometadata` makes these endpoints answer 400 invalidRequest."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['accept'] = request.headers.get('accept')
            return httpx.Response(200, json={'value': []})

        await _make_client(handler).search_sites('x')
        assert seen['accept'] == 'application/json'

    @pytest.mark.asyncio
    async def test_children_uses_getfolderbyserverrelativeurl(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(
                200, json=_folder_payload('Dokumente zur Befragung', LIB_PATH, files=[_file('a.pdf')])
            )

        listing = await _make_client(handler).list_folder_children(LIB, '')

        assert 'GetFolderByServerRelativeUrl' in seen[0]
        assert 'Folders,Files' in seen[0]
        assert [f.name for f in listing.files] == ['a.pdf']
        assert listing.files[0].id == encode_id(f'{LIB_PATH}/a.pdf')

    @pytest.mark.asyncio
    async def test_subfolder_is_addressed_by_its_server_relative_url(self):
        seen = []
        sub = f'{LIB_PATH}/Unterordner'

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json=_folder_payload('Unterordner', sub))

        await _make_client(handler).list_folder_children(LIB, encode_id(sub))
        assert 'Unterordner' in seen[0]

    @pytest.mark.asyncio
    async def test_system_folders_are_hidden(self):
        """Forms/_t/_w are SharePoint's own plumbing -- importing them would drag form
        templates and thumbnail caches into a knowledge base."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_folder_payload(
                    'Bilder',
                    '/PublishingImages',
                    folders=[_folder('Forms', '/PublishingImages'), _folder('_t', '/PublishingImages'), _folder('_w', '/PublishingImages'), _folder('Echt', '/PublishingImages')],
                ),
            )

        listing = await _make_client(handler).list_folder_children(encode_id('/PublishingImages'), '')
        assert [f.name for f in listing.folders] == ['Echt']

    @pytest.mark.asyncio
    async def test_download_by_id_hits_value_endpoint(self):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            assert 'GetFileByServerRelativeUrl' in url and url.endswith('/$value')
            return httpx.Response(200, content=b'%PDF-1.7 bytes')

        blob = await _make_client(handler).download_file_by_id(LIB, encode_id(f'{LIB_PATH}/a.pdf'))
        assert blob == b'%PDF-1.7 bytes'

    @pytest.mark.asyncio
    async def test_single_quotes_in_names_are_escaped(self):
        """A file called "Mitarbeiter's.pdf" would otherwise terminate the OData string
        literal early and the farm answers 400."""
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=b'x')

        await _make_client(handler).download_file_by_id(LIB, encode_id(f"{LIB_PATH}/Mitarbeiter's.pdf"))
        assert "''" in seen[0]

    @pytest.mark.asyncio
    async def test_recursive_walk_records_relative_paths(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if 'Sub' in str(request.url):
                return httpx.Response(
                    200,
                    json=_folder_payload(
                        'Sub', f'{LIB_PATH}/Sub', files=[_file('inner.pdf', f'{LIB_PATH}/Sub')]
                    ),
                )
            return httpx.Response(
                200,
                json=_folder_payload(
                    'Dokumente zur Befragung',
                    LIB_PATH,
                    folders=[_folder('Sub')],
                    files=[_file('top.pdf')],
                ),
            )

        listing = await _make_client(handler).list_folder(LIB, '')

        assert {(f.name, f.path) for f in listing.files} == {
            ('top.pdf', ''),
            ('inner.pdf', 'Sub/'),
        }
        assert listing.truncated is False

    @pytest.mark.asyncio
    async def test_walk_stops_at_max_files(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_folder_payload(
                    'Lib', LIB_PATH, files=[_file(f'f{i}.pdf') for i in range(10)]
                ),
            )

        listing = await _make_client(handler).list_folder(LIB, '', max_files=3)
        assert len(listing.files) == 3
        assert listing.truncated is True

    @pytest.mark.asyncio
    async def test_files_carry_no_download_url_and_a_mime_type(self):
        """On-prem has no pre-signed URL, so the importer must fall through to
        download_file_by_id -- which is the path that carries NTLM."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=_folder_payload('Lib', LIB_PATH, files=[_file('a.pdf')])
            )

        listing = await _make_client(handler).list_folder(LIB, '')
        assert listing.files[0].download_url is None
        assert listing.files[0].drive_id == LIB
        assert listing.files[0].content_type == 'application/pdf'

    @pytest.mark.asyncio
    async def test_401_on_a_bad_path_is_reported_as_not_found(self):
        """This farm answers 401 for a path that does not exist. Passing that through
        would make the caller delete a perfectly good stored credential."""
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            seen.append(url)
            if url.endswith('/_api/web/currentUser'):
                return httpx.Response(200, json={'LoginName': 'i:0#.w|d\\u'})
            return httpx.Response(401, json={})

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await _make_client(handler).list_folder_children(LIB, '')

        assert exc.value.response.status_code == 404
        assert any('currentUser' in u for u in seen)

    @pytest.mark.asyncio
    async def test_401_that_survives_the_identity_probe_stays_401(self):
        """A genuinely rejected credential must still surface as 401 so the caller drops
        the stored secret."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={})

        with pytest.raises(httpx.HTTPStatusError) as exc:
            await _make_client(handler).list_folder_children(LIB, '')

        assert exc.value.response.status_code == 401

    @pytest.mark.asyncio
    async def test_library_listing_skips_hidden_and_non_document_templates(self):
        """Measured: /_api/v2.0/.../drives reported 8 of 27 libraries and gave every one
        of them quota.used = 0, so the classic list API is used instead."""

        def handler(request: httpx.Request) -> httpx.Response:
            if '/_api/web?' in str(request.url):
                return httpx.Response(200, json={'Title': 'Portal', 'Url': BASE})
            return httpx.Response(
                200,
                json={
                    'value': [
                        {
                            'Title': 'Dokumente',
                            'BaseTemplate': 101,
                            'ItemCount': 3,
                            'Hidden': False,
                            'RootFolder': {'ServerRelativeUrl': '/Freigegebene Dokumente'},
                        },
                        {
                            'Title': 'Bilder',
                            'BaseTemplate': 851,
                            'ItemCount': 23,
                            'Hidden': False,
                            'RootFolder': {'ServerRelativeUrl': '/PublishingImages'},
                        },
                        {
                            'Title': 'Versteckt',
                            'BaseTemplate': 101,
                            'ItemCount': 5,
                            'Hidden': True,
                            'RootFolder': {'ServerRelativeUrl': '/Hidden'},
                        },
                    ]
                },
            )

        summary = await _make_client(handler).list_site_drives_summary('')
        assert [d['name'] for d in summary['drives']] == ['Dokumente']
        assert summary['drives'][0]['id'] == encode_id('/Freigegebene Dokumente')
        assert summary['drives'][0]['item_count'] == 3

    @pytest.mark.asyncio
    async def test_search_sites_filters_by_name(self):
        """No Search Service on this farm (/_api/search/query answers 500), so this is a
        name filter, not full-text search."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.endswith('/sites/root'):
                return httpx.Response(
                    200, json={'id': 'root', 'name': 'Portal', 'webUrl': BASE}
                )
            return httpx.Response(
                200,
                json={
                    'value': [
                        {'id': 's1', 'name': 'Hygiene', 'webUrl': f'{BASE}/hygiene'},
                        {'id': 's2', 'name': 'Technik', 'webUrl': f'{BASE}/technik'},
                    ]
                },
            )

        client = _make_client(handler)
        assert [s['name'] for s in await client.search_sites('hyg')] == ['Hygiene']
        assert len(await client.search_sites('*')) == 3


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_graph_client_satisfies_protocol_without_an_adapter(self):
        """The whole design rests on this: the protocol was derived from GraphClient's
        signatures, so the cloud path needs no new code at all."""
        assert isinstance(GraphClient('token'), SharePointBackend)

    def test_onprem_client_satisfies_protocol(self):
        client = SharePointOnPremClient(
            account='d\\u', password='p', base_url=BASE, http_client=httpx.AsyncClient()
        )
        assert isinstance(client, SharePointBackend)

    def test_both_clients_expose_identical_signatures(self):
        import inspect

        methods = [m for m in dir(SharePointBackend) if not m.startswith('_')]
        assert len(methods) == 9
        for name in methods:
            assert inspect.signature(getattr(GraphClient, name)) == inspect.signature(
                getattr(SharePointOnPremClient, name)
            ), f'signature drift on {name}'
