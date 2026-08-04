"""Shared fixtures for the SharePoint suites."""

import pytest

from open_webui.utils.sharepoint_onprem_client import _DISCOVERY_CACHE


@pytest.fixture(autouse=True)
def clear_discovery_cache():
    """Site discovery is cached module-wide and keyed by (farm, account, roots).

    Every test builds its client with the same three, so without this a later test reads
    an earlier test's farm and its own mock transport is never called. Autouse rather
    than opt-in: the failure mode is a test that passes for the wrong reason.
    """
    _DISCOVERY_CACHE.clear()
    yield
    _DISCOVERY_CACHE.clear()
