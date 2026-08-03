"""FORK: shared pytest wiring for the backend suite.

Importing `open_webui.internal.db` builds the async engine at module level, and on SQLite
that hands aiosqlite a **non-daemon** connection worker thread. Nothing ever closes it, so
once a test has touched the DB the interpreter blocks in `threading._shutdown()` waiting
for that thread -- *after* the suite has already reported green. Locally that looks like a
hang with no output; in CI it burns the job timeout on a passing run.

Measured on `test/sharepoint/test_sharepoint_import_onprem.py`: 6 passed in 10.9s, then the
process sat in `aiosqlite/core.py:_connection_worker_thread` until killed.
"""

import sys


def pytest_sessionfinish(session, exitstatus):
    # Only if a test actually imported the module -- importing it here would drag in the
    # whole app (and its WEBUI_SECRET_KEY requirement) for suites that never touch the DB.
    db = sys.modules.get('open_webui.internal.db')
    if db is None:
        return

    engine = getattr(db, 'async_engine', None)
    if engine is None:
        return

    import asyncio

    try:
        asyncio.run(engine.dispose())
    except Exception:
        # Teardown must never turn a green run red.
        pass
