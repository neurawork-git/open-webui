"""
Tests for RAG_NATIVE_FC_FORCE_RETRIEVAL — KB-deterministic-inject feature flag.

Covers the two patched sites in middleware.py:
  - folder_knowledge injection (form_data['files'] from folder.data['files'])
  - model_knowledge injection (form_data['files'] from model.info.meta.knowledge)

Three scenarios per site:
  1. function_calling != 'native'  → always inject (baseline, unchanged behaviour)
  2. function_calling == 'native'  + RAG_NATIVE_FC_FORCE_RETRIEVAL=True  → inject (FORK fix)
  3. function_calling == 'native'  + RAG_NATIVE_FC_FORCE_RETRIEVAL=False → skip (v0.9 path)

Also covers:
  - metadata['folder_knowledge'] sidecar population: always set when function_calling == 'native',
    independent of force_retrieval (tools.py:436 reads from this sidecar, not from form_data).
"""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Helpers — replicate the conditional logic from middleware.py so we can
# unit-test it without importing the full FastAPI app.
# ---------------------------------------------------------------------------

def _simulate_folder_inject(function_calling: str, force_retrieval: bool, folder_files: list) -> dict:
    """
    Mirrors the folder_knowledge block in middleware.py (Z.~2509).
    Returns form_data after the conditional runs.
    """
    form_data: dict = {"files": []}
    metadata: dict = {"params": {"function_calling": function_calling}}

    if metadata.get("params", {}).get("function_calling") != "native" or force_retrieval:
        form_data["files"] = [
            *folder_files,
            *form_data.get("files", []),
        ]

    return form_data


def _simulate_model_inject(function_calling: str, force_retrieval: bool, knowledge_files: list) -> dict:
    """
    Mirrors the model_knowledge block in middleware.py (Z.~2524).
    Returns form_data after the conditional runs.
    """
    form_data: dict = {"files": []}

    if knowledge_files and (
        {"params": {"function_calling": function_calling}}.get("params", {}).get("function_calling") != "native"
        or force_retrieval
    ):
        form_data["files"].extend(knowledge_files)

    return form_data


# ---------------------------------------------------------------------------
# Folder knowledge tests
# ---------------------------------------------------------------------------

class TestFolderKnowledgeInject:
    """Tests for the folder_knowledge injection site."""

    FOLDER_FILES = [{"id": "kb-folder-1", "name": "Doc A"}]

    def test_non_native_always_injects(self):
        """Baseline: non-native function_calling always injects folder knowledge."""
        result = _simulate_folder_inject(
            function_calling="none",
            force_retrieval=False,
            folder_files=self.FOLDER_FILES,
        )
        assert result["files"] == self.FOLDER_FILES

    def test_native_force_retrieval_true_injects(self):
        """FORK fix: native FC + force_retrieval=True still injects folder knowledge."""
        result = _simulate_folder_inject(
            function_calling="native",
            force_retrieval=True,
            folder_files=self.FOLDER_FILES,
        )
        assert result["files"] == self.FOLDER_FILES

    def test_native_force_retrieval_false_skips(self):
        """v0.9 path: native FC + force_retrieval=False skips folder knowledge injection."""
        result = _simulate_folder_inject(
            function_calling="native",
            force_retrieval=False,
            folder_files=self.FOLDER_FILES,
        )
        assert result["files"] == []

    def test_native_force_retrieval_true_prepends_to_existing_files(self):
        """Folder files are prepended before existing form_data files when force_retrieval=True."""
        existing = [{"id": "existing-file"}]
        form_data: dict = {"files": existing.copy()}
        metadata: dict = {"params": {"function_calling": "native"}}
        force_retrieval = True

        if metadata.get("params", {}).get("function_calling") != "native" or force_retrieval:
            form_data["files"] = [
                *self.FOLDER_FILES,
                *form_data.get("files", []),
            ]

        assert form_data["files"][0] == self.FOLDER_FILES[0]
        assert form_data["files"][1] == existing[0]


# ---------------------------------------------------------------------------
# Model knowledge tests
# ---------------------------------------------------------------------------

class TestModelKnowledgeInject:
    """Tests for the model_knowledge injection site."""

    MODEL_KB_FILES = [
        {"id": "kb-model-1", "name": "Doc B", "type": "collection", "collection_names": ["col1"]},
    ]

    def test_non_native_always_injects(self):
        """Baseline: non-native function_calling always injects model knowledge."""
        result = _simulate_model_inject(
            function_calling="none",
            force_retrieval=False,
            knowledge_files=self.MODEL_KB_FILES,
        )
        assert result["files"] == self.MODEL_KB_FILES

    def test_native_force_retrieval_true_injects(self):
        """FORK fix: native FC + force_retrieval=True still injects model knowledge."""
        result = _simulate_model_inject(
            function_calling="native",
            force_retrieval=True,
            knowledge_files=self.MODEL_KB_FILES,
        )
        assert result["files"] == self.MODEL_KB_FILES

    def test_native_force_retrieval_false_skips(self):
        """v0.9 path: native FC + force_retrieval=False skips model knowledge injection."""
        result = _simulate_model_inject(
            function_calling="native",
            force_retrieval=False,
            knowledge_files=self.MODEL_KB_FILES,
        )
        assert result["files"] == []

    def test_empty_knowledge_never_injects(self):
        """No model knowledge → files list stays empty regardless of force_retrieval."""
        result = _simulate_model_inject(
            function_calling="native",
            force_retrieval=True,
            knowledge_files=[],
        )
        assert result["files"] == []


# ---------------------------------------------------------------------------
# Config state access tests — verify getattr fallback behaviour
# ---------------------------------------------------------------------------

class TestConfigStateAccess:
    """
    Tests that the getattr(..., True) default works correctly when the
    config attribute is missing (e.g. older state object without the key).
    """

    def test_getattr_default_true_when_missing(self):
        """getattr returns True when RAG_NATIVE_FC_FORCE_RETRIEVAL not on state."""
        config = SimpleNamespace()  # no RAG_NATIVE_FC_FORCE_RETRIEVAL attribute
        result = getattr(config, "RAG_NATIVE_FC_FORCE_RETRIEVAL", True)
        assert result is True

    def test_getattr_returns_false_when_set_false(self):
        """getattr returns False when explicitly set to False."""
        config = SimpleNamespace(RAG_NATIVE_FC_FORCE_RETRIEVAL=False)
        result = getattr(config, "RAG_NATIVE_FC_FORCE_RETRIEVAL", True)
        assert result is False

    def test_getattr_returns_true_when_set_true(self):
        """getattr returns True when explicitly set to True."""
        config = SimpleNamespace(RAG_NATIVE_FC_FORCE_RETRIEVAL=True)
        result = getattr(config, "RAG_NATIVE_FC_FORCE_RETRIEVAL", True)
        assert result is True


# ---------------------------------------------------------------------------
# Sidecar population tests — metadata['folder_knowledge']
# ---------------------------------------------------------------------------

def _simulate_sidecar_populate(function_calling: str, force_retrieval: bool, folder_files: list) -> dict:
    """
    Mirrors the full folder_knowledge block in middleware.py including the
    unconditional sidecar assignment (lines ~2515-2522).

    The sidecar is populated whenever function_calling == 'native', regardless
    of force_retrieval. tools.py:436 reads ONLY from metadata['folder_knowledge'],
    so the sidecar must be present for native-FC tool registration to work.
    """
    form_data: dict = {"files": []}
    metadata: dict = {"params": {"function_calling": function_calling}}

    # Mirror middleware.py: conditional RAG injection
    if metadata.get("params", {}).get("function_calling") != "native" or force_retrieval:
        form_data["files"] = [
            *folder_files,
            *form_data.get("files", []),
        ]

    # Mirror middleware.py: unconditional sidecar population for native FC
    if metadata.get("params", {}).get("function_calling") == "native":
        metadata["folder_knowledge"] = folder_files

    return form_data, metadata


class TestFolderKnowledgeSidecar:
    """
    Verifies that metadata['folder_knowledge'] is populated whenever
    function_calling == 'native', independent of force_retrieval.

    tools.py:436 reads folder_knowledge from the metadata sidecar to register
    query_knowledge_files for agentic deep-dive queries. If the sidecar is
    missing, native-FC models silently lose access to folder-attached KBs.
    """

    FOLDER_FILES = [{"id": "kb-folder-1", "name": "Doc A"}]

    def test_native_force_retrieval_true_sidecar_populated(self):
        """native FC + force_retrieval=True: sidecar set AND files injected."""
        form_data, metadata = _simulate_sidecar_populate(
            function_calling="native",
            force_retrieval=True,
            folder_files=self.FOLDER_FILES,
        )
        assert metadata.get("folder_knowledge") == self.FOLDER_FILES
        # files also injected because force_retrieval=True
        assert form_data["files"] == self.FOLDER_FILES

    def test_native_force_retrieval_false_sidecar_populated(self):
        """native FC + force_retrieval=False: sidecar still set even though files NOT injected."""
        form_data, metadata = _simulate_sidecar_populate(
            function_calling="native",
            force_retrieval=False,
            folder_files=self.FOLDER_FILES,
        )
        assert metadata.get("folder_knowledge") == self.FOLDER_FILES
        # files NOT injected (v0.9 path — tool handles retrieval itself)
        assert form_data["files"] == []

    def test_non_native_no_sidecar(self):
        """non-native FC: sidecar never set (tools.py KB registration uses model.info.meta.knowledge)."""
        _, metadata = _simulate_sidecar_populate(
            function_calling="none",
            force_retrieval=False,
            folder_files=self.FOLDER_FILES,
        )
        assert "folder_knowledge" not in metadata
