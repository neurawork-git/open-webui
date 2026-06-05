"""Regression tests for processing router registration in main.py.

The processing router was previously commented out in main.py (TODO to port
sync->async sessions), which made /admin/processing in the frontend return 404
for every call. The unit tests in test_processing_api.py don't catch that
because they mount the router on a private FastAPI() inside the test file —
they pass even when the production app doesn't include the router.

These tests assert registration on the *real* main app so future comment-outs
of the router cannot regress silently.
"""

from __future__ import annotations

import re
from pathlib import Path


ROUTERS_DIR = Path(__file__).resolve().parents[2] / "routers"
MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"
PROCESSING_PY = ROUTERS_DIR / "processing.py"


def _main_py_source() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def _processing_py_source() -> str:
    return PROCESSING_PY.read_text(encoding="utf-8")


def test_main_py_imports_processing_module():
    """main.py must import `processing` alongside the other routers."""
    src = _main_py_source()
    # The import lives in the `from open_webui.routers import (...)` block.
    # We require the module to appear as an unindented list entry (no leading '#').
    assert "\n    processing,\n" in src, (
        "processing router is not imported in main.py. "
        "Add `processing,` to `from open_webui.routers import (...)`."
    )
    assert "# processing," not in src and "#processing," not in src, (
        "processing import is commented out in main.py."
    )


def test_main_py_includes_processing_router():
    """main.py must register the processing router under /api/v1/admin/processing."""
    src = _main_py_source()
    expected = (
        "app.include_router(processing.router, "
        "prefix='/api/v1/admin/processing', tags=['processing'])"
    )
    assert expected in src, (
        "processing router is not registered in main.py. "
        f"Expected line:\n  {expected}"
    )
    # Belt-and-suspenders: the exact registration line must not be commented.
    assert f"# {expected}" not in src and f"#{expected}" not in src, (
        "processing router include_router line is commented out."
    )


def test_processing_router_exposes_frontend_routes():
    """The router must declare the endpoints the frontend calls.

    File-based (no import) because importing open_webui.routers.processing
    transitively re-registers the `config` Table on Base.metadata in some
    environments, causing a collection error unrelated to this test.
    """
    src = _processing_py_source()
    expected_decorators = [
        '@router.get("/tasks"',
        '@router.get("/tasks/{task_id}"',
        '@router.post("/tasks/{task_id}/cancel"',
        '@router.post("/tasks/{task_id}/retry"',
        '@router.post("/tasks/bulk/cancel"',
        '@router.post("/tasks/bulk/retry"',
        '@router.post("/tasks/bulk/delete"',
        '@router.delete("/tasks/{task_id}"',
        '@router.get("/metrics"',
        '@router.post("/cleanup"',
    ]
    missing = [d for d in expected_decorators if d not in src]
    assert not missing, f"processing router is missing decorators: {missing}"


def test_all_processing_handlers_are_async():
    """Every @router.<verb>(...) decorated handler must be `async def`.

    Sync handlers on AsyncSession dependencies would block the event loop
    and re-introduce the port-to-async bug that once caused the router to
    be disabled in main.py.
    """
    src = _processing_py_source()
    # Match `@router.<verb>("...")` followed (optionally by decorator args /
    # blank lines) by a `def` or `async def` declaration.
    pattern = re.compile(
        r'^@router\.(?:get|post|put|delete|patch)\([^\n]*\)[\s\S]*?^(?P<defline>(?:async\s+)?def\s+(?P<name>\w+))',
        re.MULTILINE,
    )
    sync_handlers = [
        m.group("name")
        for m in pattern.finditer(src)
        if not m.group("defline").lstrip().startswith("async ")
    ]
    assert not sync_handlers, (
        f"These processing handlers must be `async def`: {sync_handlers}"
    )


def test_retry_handler_awaits_get_user_by_id():
    """Regression: a missing `await` on Users.get_user_by_id silently stored a
    coroutine in `file_user`, then passed it as the background-task user."""
    src = _processing_py_source()
    assert "await Users.get_user_by_id" in src, (
        "retry_processing_task must `await Users.get_user_by_id(...)` — "
        "Users.get_user_by_id is async."
    )
    # The previous implementation referenced a non-existent `_process_file_impl`
    # helper inside the background task, which would NameError at runtime.
    assert "_process_file_impl" not in src, (
        "processing.py references an undefined _process_file_impl; "
        "use routers.retrieval.process_file instead."
    )
