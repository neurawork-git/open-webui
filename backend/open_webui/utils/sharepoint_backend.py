"""Resolves which SharePoint backend a user's request runs against (fork-local).

Before this module, `routers/knowledge.py` produced a Microsoft Graph bearer token and
passed it to `GraphClient` at nine call sites.  That works for tenants on Entra; it cannot
work for an on-prem farm that only offers NTLM.  So the nine call sites now ask for a
*backend* instead of a token, and this module decides where it comes from:

    SHAREPOINT_BACKEND=graph   -> GraphClient with a delegated OAuth token  (unchanged)
    SHAREPOINT_BACKEND=onprem  -> SharePointOnPremClient with the user's stored AD credential

The `SharePointBackend` protocol below is derived verbatim from `GraphClient`'s existing
signatures.  That is deliberate: it means `GraphClient` satisfies it with no adapter and no
change, so the cloud path carries zero new code and zero regression risk.  Only the on-prem
implementation is new work.

The decrypted password never leaves this module.  Tools receive a ready client from
`get_sharepoint_backend_for_user`, never a credential -- a tool has no use for a string it
would only have to build a client from.
"""

import logging
from typing import Optional, Protocol, runtime_checkable

from fastapi import HTTPException, Request, status
from open_webui.env import (
    ENABLE_LDAP_CREDENTIAL_STORE,
    LDAP_NETBIOS_DOMAIN,
    SHAREPOINT_BACKEND,
    SHAREPOINT_ONPREM_SITE_URL,
    SHAREPOINT_ONPREM_VERIFY_TLS,
)
from open_webui.config import Config
from open_webui.models.oauth_sessions import OAuthSessions
from open_webui.utils.graph_client import (
    GraphChildrenListing,
    GraphClient,
    GraphFileItem,
    GraphFolderListing,
    GraphSiteListing,
)
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


@runtime_checkable
class SharePointBackend(Protocol):
    """The subset of GraphClient that routers/knowledge.py actually calls.

    Nine methods -- the exact output of
    `grep -n "await graph\\." backend/open_webui/routers/knowledge.py`.  Do not grow this
    without a caller: every method added here becomes an obligation for the on-prem
    implementation too.
    """

    async def list_folder(
        self, drive_id: str, item_id: str, max_files: int = 1000
    ) -> GraphFolderListing: ...

    async def list_site(self, site_id: str, max_files: int = 1000) -> GraphSiteListing: ...

    async def search_sites(self, query: str, top: int = 25) -> list[dict]: ...

    async def list_sites_paginated(
        self, query: str = '*', top: int = 100, next_link: Optional[str] = None
    ) -> dict: ...

    async def list_site_drives_summary(self, site_id: str) -> dict: ...

    async def list_folder_children(
        self,
        drive_id: str,
        item_id: str,
        top: int = 200,
        next_link: Optional[str] = None,
    ) -> GraphChildrenListing: ...

    async def get_file_metadata(
        self, drive_id: str, item_id: str, path: str = ''
    ) -> GraphFileItem: ...

    async def download_file(self, download_url: str) -> bytes: ...

    async def download_file_by_id(self, drive_id: str, item_id: str) -> bytes: ...


def is_onprem() -> bool:
    return SHAREPOINT_BACKEND.strip().lower() == 'onprem'


####################
# Write path (LDAP login)
####################


async def maybe_store_ldap_credential(
    user, entry_username: str, password: str, db: Optional[AsyncSession] = None
) -> None:
    """Capture the AD password at LDAP login.

    Storing is the DEFAULT wherever the feature flag is on -- there is no consent dialog.
    The only thing that suppresses it is an explicit opt-out the user set earlier, which is
    why that refusal is persisted rather than inferred: otherwise deleting a credential
    would be undone by the very next login.

    Called from `routers/auths.py::ldap_auth` as a single line, on purpose: that function is
    an upstream hotspot and every extra line is merge-conflict surface.

    Never raises. A broken credential store must not lock anybody out of Open WebUI.
    """
    if not ENABLE_LDAP_CREDENTIAL_STORE:
        return

    try:
        from open_webui.models.user_credentials import get_user_credentials

        credentials = get_user_credentials()
        if await credentials.is_opted_out(user.id, db=db):
            log.debug('User %s opted out of credential storage', user.id)
            return

        account = entry_username.strip()
        if account and '\\' not in account and '@' not in account and LDAP_NETBIOS_DOMAIN:
            account = f'{LDAP_NETBIOS_DOMAIN}\\{account}'

        await credentials.upsert(user_id=user.id, account=account, secret=password, db=db)
        log.info('Stored LDAP credential for user %s (account %s)', user.id, account)
    except Exception as e:
        # Deliberately swallowed: the login itself must succeed regardless.
        log.error('Could not store LDAP credential: %s', type(e).__name__)


####################
# Read path (resolver)
####################


async def _graph_backend(request: Request, user, db) -> SharePointBackend:
    """The pre-existing OAuth path, moved here verbatim from knowledge.py.

    Uses OAuthManager (the manager that actually owns the Microsoft client via
    OAUTH_PROVIDERS['microsoft']) and its existing session-id-based get_oauth_token path --
    so refresh + delete-on-fail policy stay in one place. Session id comes from the
    oauth_session_id cookie set at login; if that cookie is gone we fall back to the newest
    stored Microsoft session for this user.
    """
    oauth_manager = getattr(request.app.state, 'oauth_manager', None)
    if oauth_manager is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='OAuth manager not initialised.',
        )

    session_id = request.cookies.get('oauth_session_id')
    if not session_id:
        fallback = await OAuthSessions.get_session_by_provider_and_user_id(
            provider='microsoft', user_id=user.id, db=db
        )
        session_id = fallback.id if fallback else None

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='No Microsoft OAuth session found. Please log in with Microsoft SSO first.',
        )

    token = await oauth_manager.get_oauth_token(user.id, session_id)
    access_token = token.get('access_token') if isinstance(token, dict) else None
    if access_token:
        return GraphClient(access_token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            'Microsoft OAuth token could not be retrieved or refreshed. '
            'Sign out of Open WebUI and sign back in via Microsoft to '
            're-establish the session.'
        ),
    )


def _assert_onprem_configured() -> None:
    """Fail loudly rather than falling back to Graph, which would silently send on-prem
    users to a tenant that knows nothing about them."""
    if not SHAREPOINT_ONPREM_SITE_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail='SHAREPOINT_BACKEND=onprem but SHAREPOINT_ONPREM_SITE_URL is not set.',
        )
    if not ENABLE_LDAP_CREDENTIAL_STORE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                'SHAREPOINT_BACKEND=onprem requires ENABLE_LDAP_CREDENTIAL_STORE=true -- '
                'there is no other way to obtain the user credential.'
            ),
        )


async def _onprem_backend(user_id: str, db=None) -> SharePointBackend:
    _assert_onprem_configured()

    # Imported here, not at module scope: the NTLM stack is only a dependency for
    # deployments that actually talk to an on-prem farm.
    from open_webui.models.user_credentials import get_user_credentials
    from open_webui.utils.sharepoint_onprem_client import (
        SharePointOnPremClient,
        parse_site_roots,
    )

    credential = await get_user_credentials().get_secret(user_id, db=db)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                'Kein hinterlegtes AD-Kennwort. Bitte in Open WebUI abmelden und erneut '
                'per LDAP anmelden — dabei wird das Kennwort wieder hinterlegt. Falls die '
                'Speicherung in den Kontoeinstellungen deaktiviert wurde, dort zuerst '
                'wieder aktivieren.'
            ),
        )

    account, password = credential
    # Read per request, not cached on the module: an entry point added in the admin panel
    # has to take effect on the next call, without a restart.
    site_roots = parse_site_roots(await Config.get('sharepoint.onprem.site_roots'))
    return SharePointOnPremClient(
        account=account,
        password=password,
        base_url=SHAREPOINT_ONPREM_SITE_URL,
        verify=SHAREPOINT_ONPREM_VERIFY_TLS,
        site_roots=site_roots,
    )


async def forget_credential_after_rejection(user_id: str, db=None) -> None:
    """Drop the stored credential after the farm rejected it.

    The whole no-retry policy is this function plus its single caller: a rejected password
    is deleted, never retried.  A retry loop would spend the domain's five allowed
    failures in seconds and lock the user out for fifteen minutes.
    """
    if not is_onprem():
        return
    try:
        from open_webui.models.user_credentials import get_user_credentials

        await get_user_credentials().delete(user_id, db=db)
        log.warning('SharePoint rejected the stored credential for %s; deleted it', user_id)
    except Exception as e:
        log.error('Could not delete rejected credential: %s', type(e).__name__)


async def get_sharepoint_backend(request: Request, user, db) -> SharePointBackend:
    """The single place a SharePoint credential enters a request. Replaces the former
    `_get_microsoft_access_token` + `GraphClient(...)` pair at every call site."""
    if is_onprem():
        return await _onprem_backend(user.id, db=db)
    return await _graph_backend(request, user, db)


async def get_sharepoint_backend_for_user(
    user_id: str, db=None
) -> Optional[SharePointBackend]:
    """Backend for contexts without a Request -- tool calls, background work.

    Returns None instead of raising: a tool that cannot reach SharePoint should say so in
    its own answer, not blow up the surrounding chat.  Only the on-prem path is served
    here; the Graph path needs the request cookie and keeps using
    `middleware.get_system_oauth_token`.
    """
    if not is_onprem():
        return None
    try:
        return await _onprem_backend(user_id, db=db)
    except HTTPException as e:
        log.info('No SharePoint backend for user %s: %s', user_id, e.detail)
        return None
    except Exception as e:
        log.error('Error building SharePoint backend: %s', type(e).__name__)
        return None
