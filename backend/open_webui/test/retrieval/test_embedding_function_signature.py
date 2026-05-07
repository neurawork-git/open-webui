"""
Regression tests for the async_embedding_function tracker parameter bug.

Bug: async_embedding_function (defined inside get_embedding_function for the
ollama/openai/azure_openai branch) referenced `tracker` in its body but did NOT
declare it as a parameter. On first call the enclosing scope had no `tracker`
binding -> NameError -> HTTP 400 "Hybrid search failed for all collections".

Fixed in: backend/open_webui/retrieval/utils.py, line 1658
Fix: added `tracker=None` to async_embedding_function signature.

Tests verify:
  1. Single-string query path does not raise NameError (no tracker passed)
  2. List-query path (batch, enable_async=True) does not raise NameError
  3. List-query path (batch, enable_async=False) does not raise NameError
  4. When tracker is passed, is_cancelled() is forwarded correctly
  5. Engines openai, azure_openai, ollama all covered
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper — build the async_embedding_function returned by get_embedding_function
# without importing the full app (avoids DB/config side-effects).
#
# IMPORTANT: the lambda inside get_embedding_function captures generate_embeddings
# as a module-level name that is resolved at *call* time, not at construction
# time.  Therefore the patch must remain active while fn(...) is being called,
# not just during get_embedding_function().  _make_fn uses patcher.start() and
# returns a stop-callable so callers can tear down after the call.
# ---------------------------------------------------------------------------

MODULE = "open_webui.retrieval.utils"


def _make_fn(engine: str, enable_async: bool = True, concurrent_requests: int = 0):
    """
    Return (async_embedding_function, mock_generate_embeddings, stop_patch).

    stop_patch() MUST be called after fn(...) has been awaited, to restore the
    original generate_embeddings symbol.
    """
    from open_webui.retrieval.utils import get_embedding_function

    mock_gen = AsyncMock()

    def _side_effect(*args, **kwargs):
        text = kwargs.get("text", args[1] if len(args) > 1 else None)
        if isinstance(text, list):
            return [[float(i) * 0.1, float(i) * 0.2] for i in range(len(text))]
        return [0.1, 0.2, 0.3]

    mock_gen.side_effect = _side_effect

    patcher = patch(f"{MODULE}.generate_embeddings", mock_gen)
    patcher.start()

    fn = get_embedding_function(
        embedding_engine=engine,
        embedding_model="test-model",
        embedding_function=None,
        url="http://localhost",
        key="test-key",
        embedding_batch_size=10,
        azure_api_version="2024-02-01",
        enable_async=enable_async,
        concurrent_requests=concurrent_requests,
    )

    return fn, mock_gen, patcher.stop


# ---------------------------------------------------------------------------
# 1. String query — no tracker argument (the common hot-path that was crashing)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ["openai", "azure_openai", "ollama"])
def test_async_embedding_function_string_query_no_tracker_param(engine):
    """
    Single-string query without tracker must not raise NameError.
    This is the exact production failure scenario.
    """
    fn, mock_gen, stop = _make_fn(engine)
    try:
        result = asyncio.get_event_loop().run_until_complete(fn("test query"))
    finally:
        stop()

    # Should return the mock embedding without crashing
    assert result is not None
    assert mock_gen.called


# ---------------------------------------------------------------------------
# 2. List query — enable_async=True (parallel batch path, lines 1677-1691)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ["openai", "azure_openai", "ollama"])
def test_async_embedding_function_list_query_no_tracker_async(engine):
    """
    List query with enable_async=True must not raise NameError.
    Covers the gather() batch path at lines 1683-1691.
    """
    fn, mock_gen, stop = _make_fn(engine, enable_async=True, concurrent_requests=0)
    try:
        chunks = ["chunk1", "chunk2", "chunk3"]
        result = asyncio.get_event_loop().run_until_complete(fn(chunks))
    finally:
        stop()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == len(chunks)


@pytest.mark.parametrize("engine", ["openai", "azure_openai", "ollama"])
def test_async_embedding_function_list_query_no_tracker_async_semaphore(engine):
    """
    List query with enable_async=True + concurrent_requests>0 must not raise NameError.
    Covers the semaphore-wrapped batch path at lines 1677-1685.
    """
    fn, mock_gen, stop = _make_fn(engine, enable_async=True, concurrent_requests=2)
    try:
        chunks = ["chunk1", "chunk2", "chunk3"]
        result = asyncio.get_event_loop().run_until_complete(fn(chunks))
    finally:
        stop()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == len(chunks)


# ---------------------------------------------------------------------------
# 3. List query — enable_async=False (sequential path, lines 1693-1701)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ["openai", "azure_openai", "ollama"])
def test_async_embedding_function_list_query_no_tracker_sequential(engine):
    """
    List query with enable_async=False must not raise NameError.
    Covers the sequential for-loop batch path at line 1696.
    Note: sequential path does NOT forward tracker (pre-existing behaviour).
    """
    fn, mock_gen, stop = _make_fn(engine, enable_async=False)
    try:
        chunks = ["chunk1", "chunk2"]
        result = asyncio.get_event_loop().run_until_complete(fn(chunks))
    finally:
        stop()

    assert result is not None
    assert isinstance(result, list)
    assert len(result) == len(chunks)


# ---------------------------------------------------------------------------
# 4. Tracker is forwarded correctly when passed
# ---------------------------------------------------------------------------

def test_async_embedding_function_with_tracker_passed():
    """
    When a tracker is passed to async_embedding_function, it must be forwarded
    to generate_embeddings via the embedding_function lambda.
    Covers the string-query path at line 1722.
    """
    mock_tracker = MagicMock()
    mock_tracker.is_cancelled.return_value = False

    fn, mock_gen, stop = _make_fn("openai")
    try:
        asyncio.get_event_loop().run_until_complete(fn("test query", tracker=mock_tracker))
    finally:
        stop()

    # Verify tracker was forwarded (generate_embeddings receives tracker=mock_tracker)
    assert mock_gen.called
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs.get("tracker") is mock_tracker


def test_async_embedding_function_with_tracker_passed_list_async():
    """
    Tracker forwarded in async batch path (lines 1679-1688).
    """
    mock_tracker = MagicMock()
    mock_tracker.is_cancelled.return_value = False

    fn, mock_gen, stop = _make_fn("openai", enable_async=True, concurrent_requests=0)
    try:
        asyncio.get_event_loop().run_until_complete(
            fn(["chunk1", "chunk2"], tracker=mock_tracker)
        )
    finally:
        stop()

    assert mock_gen.called
    # All batch calls should have received tracker
    for c in mock_gen.call_args_list:
        assert c.kwargs.get("tracker") is mock_tracker


# ---------------------------------------------------------------------------
# 5. Engine-matrix: azure_openai explicit — was the primary crash engine
# ---------------------------------------------------------------------------

def test_async_embedding_function_azure_openai_engine_string():
    """
    azure_openai engine with single string query must not raise NameError.
    Primary production crash scenario (Falkensteg).
    """
    fn, mock_gen, stop = _make_fn("azure_openai")
    try:
        result = asyncio.get_event_loop().run_until_complete(fn("what is the policy?"))
    finally:
        stop()
    assert result is not None


def test_async_embedding_function_azure_openai_engine_list():
    """
    azure_openai engine with list query must not raise NameError.
    """
    fn, mock_gen, stop = _make_fn("azure_openai")
    try:
        result = asyncio.get_event_loop().run_until_complete(
            fn(["policy section 1", "policy section 2"])
        )
    finally:
        stop()
    assert isinstance(result, list)
    assert len(result) == 2


def test_async_embedding_function_ollama_engine_string():
    """ollama engine with single string query must not raise NameError."""
    fn, mock_gen, stop = _make_fn("ollama")
    try:
        result = asyncio.get_event_loop().run_until_complete(fn("frage an das modell"))
    finally:
        stop()
    assert result is not None


def test_async_embedding_function_ollama_engine_list():
    """ollama engine with list query must not raise NameError."""
    fn, mock_gen, stop = _make_fn("ollama")
    try:
        result = asyncio.get_event_loop().run_until_complete(fn(["chunk_a", "chunk_b", "chunk_c"]))
    finally:
        stop()
    assert isinstance(result, list)
    assert len(result) == 3
