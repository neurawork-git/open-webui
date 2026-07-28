"""FORK: runtime-editable custom CSS.

Upstream already ships ``<link rel="stylesheet" href="/static/custom.css">`` in
``src/app.html`` — but it is backed by a file in ``STATIC_DIR``, which ``config.py``
wipes on every backend import (see ``docs/FORK_CHANGES.md`` §11.1). So the only way
to brand an instance was to bake CSS into the image, i.e. a design fork per customer.

This router serves that same URL from the ``config`` table instead. Branding becomes
a config write: API-editable at runtime, no rebuild, no redeploy, no fork. Because it
stays a separate stylesheet (rather than being inlined into a ``<style>`` block), the
CSS needs no HTML escaping and cannot break out of its context.

Endpoints:
  GET  /static/custom.css   public   the stylesheet itself (linked by app.html)
  GET  /api/v1/custom-css   admin    {"css": "..."} for the editor
  POST /api/v1/custom-css   admin    {"css": "..."} to replace it
"""

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from open_webui.models.config import Config
from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)

router = APIRouter()

CONFIG_KEY = 'ui.custom_css'

# Generous enough for a full theme, small enough that a fat-fingered paste cannot
# turn every page load into a megabyte download.
MAX_CSS_BYTES = 256 * 1024


class CustomCssForm(BaseModel):
    css: str


async def _stored_css() -> str:
    value = await Config.get(CONFIG_KEY, '')
    # The config column is JSON, so a non-string could be written through the generic
    # config import endpoint. Serving that as CSS would be nonsense — treat it as unset.
    return value if isinstance(value, str) else ''


@router.get('/static/custom.css')
async def get_custom_stylesheet(request: Request):
    """The stylesheet upstream's own app.html already links.

    Registered before ``app.mount('/static', ...)`` in main.py so it shadows the
    (wiped, empty) file of the same name. Applies pre-auth and before first paint
    without any frontend wiring.
    """
    css = await _stored_css()
    etag = f'"{hashlib.sha256(css.encode("utf-8")).hexdigest()[:32]}"'
    headers = {
        # Revalidate on every load so an edit goes live immediately; the ETag keeps
        # the usual case a 304 rather than a re-download.
        'Cache-Control': 'no-cache',
        'ETag': etag,
        'X-Content-Type-Options': 'nosniff',
    }

    if request.headers.get('if-none-match') == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return Response(content=css, media_type='text/css', headers=headers)


@router.get('/api/v1/custom-css')
async def get_custom_css(user=Depends(get_admin_user)):
    return {'css': await _stored_css()}


@router.post('/api/v1/custom-css')
async def set_custom_css(form_data: CustomCssForm, user=Depends(get_admin_user)):
    css = form_data.css or ''
    size = len(css.encode('utf-8'))

    if size > MAX_CSS_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f'Custom CSS is {size} bytes; the limit is {MAX_CSS_BYTES}.',
        )

    await Config.upsert({CONFIG_KEY: css})
    log.info('Custom CSS updated by user %s (%d bytes)', user.id, size)

    return {'css': css}
