"""
Unit tests for RAGQuerySettings model from retrieval/models.py.

Tests the unified settings object used in RAG query functions.
"""

import pytest
from open_webui.retrieval.models import RAGQuerySettings


class TestRAGQuerySettings:
    """Tests for the unified RAGQuerySettings model used in retrieval functions."""

    def test_default_values(self):
        """Test default values for RAGQuerySettings."""
        settings = RAGQuerySettings()
        assert settings.top_k == 3
        assert settings.top_k_reranker == 3
        assert settings.relevance_threshold == 0.0
        assert settings.enable_hybrid_search is False
        assert settings.hybrid_bm25_weight == 0.5
        assert settings.enable_enriched_texts is False
        assert settings.enable_reranking is True
        assert settings.full_context is False

    def test_custom_values(self):
        """Test custom values for RAGQuerySettings."""
        settings = RAGQuerySettings(
            top_k=10,
            top_k_reranker=5,
            relevance_threshold=0.7,
            enable_hybrid_search=True,
            hybrid_bm25_weight=0.3,
            enable_enriched_texts=True,
            enable_reranking=False,
            full_context=True,
        )
        assert settings.top_k == 10
        assert settings.top_k_reranker == 5
        assert settings.relevance_threshold == 0.7
        assert settings.enable_hybrid_search is True
        assert settings.hybrid_bm25_weight == 0.3
        assert settings.enable_enriched_texts is True
        assert settings.enable_reranking is False
        assert settings.full_context is True

    def test_merge_with_overrides(self):
        """Test merge_with method applies overrides correctly."""
        base = RAGQuerySettings(top_k=5, relevance_threshold=0.5)
        merged = base.merge_with({"top_k": 10, "enable_hybrid_search": True})

        assert merged.top_k == 10  # Overridden
        assert merged.relevance_threshold == 0.5  # Preserved
        assert merged.enable_hybrid_search is True  # Overridden

    def test_merge_with_none_values_ignored(self):
        """Test that None values in overrides are ignored."""
        base = RAGQuerySettings(top_k=5)
        merged = base.merge_with({"top_k": None, "relevance_threshold": 0.8})

        assert merged.top_k == 5  # Not overridden (None ignored)
        assert merged.relevance_threshold == 0.8  # Overridden

    def test_merge_with_alternative_keys(self):
        """Test merge_with supports alternative key names."""
        base = RAGQuerySettings()
        merged = base.merge_with({
            "k": 10,  # Alternative for top_k
            "r": 0.7,  # Alternative for relevance_threshold
            "hybrid": True,  # Alternative for enable_hybrid_search
        })

        assert merged.top_k == 10
        assert merged.relevance_threshold == 0.7
        assert merged.enable_hybrid_search is True

    def test_to_query_params(self):
        """Test to_query_params converts to query function format."""
        settings = RAGQuerySettings(
            top_k=10,
            top_k_reranker=5,
            relevance_threshold=0.7,
            hybrid_bm25_weight=0.4,
        )
        params = settings.to_query_params()

        assert params["k"] == 10
        assert params["k_reranker"] == 5
        assert params["r"] == 0.7
        assert params["hybrid_bm25_weight"] == 0.4

    def test_model_dump(self):
        """Test model_dump produces correct dict."""
        settings = RAGQuerySettings(top_k=5, enable_hybrid_search=True)
        data = settings.model_dump()

        assert data["top_k"] == 5
        assert data["enable_hybrid_search"] is True
        assert "relevance_threshold" in data  # All fields present

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored (forward compatibility)."""
        settings = RAGQuerySettings(
            top_k=5,
            unknown_field="ignored",  # type: ignore
        )
        assert settings.top_k == 5
        assert not hasattr(settings, "unknown_field")

    def test_chained_merge(self):
        """Test chaining multiple merge_with calls."""
        global_settings = RAGQuerySettings(top_k=3, relevance_threshold=0.0)
        user_settings = global_settings.merge_with({"top_k": 5})
        kb_settings = user_settings.merge_with({"relevance_threshold": 0.5, "enable_hybrid_search": True})

        assert kb_settings.top_k == 5  # From user
        assert kb_settings.relevance_threshold == 0.5  # From KB
        assert kb_settings.enable_hybrid_search is True  # From KB


class TestRAGQuerySettingsIntegration:
    """Integration tests for RAGQuerySettings with utils functions."""

    def test_import_settings_based_functions(self):
        """Test that the new settings-based functions can be imported."""
        from open_webui.retrieval.utils import (
            RAGQuerySettings,
            query_doc_with_hybrid_search_settings,
            query_collection_with_hybrid_search_settings,
            get_sources_from_items_with_settings,
        )
        # Just verify imports work
        assert RAGQuerySettings is not None
        assert query_doc_with_hybrid_search_settings is not None
        assert query_collection_with_hybrid_search_settings is not None
        assert get_sources_from_items_with_settings is not None

    def test_settings_to_function_params_mapping(self):
        """Test that RAGQuerySettings maps correctly to function parameters."""
        settings = RAGQuerySettings(
            top_k=10,
            top_k_reranker=5,
            relevance_threshold=0.7,
            enable_hybrid_search=True,
            hybrid_bm25_weight=0.3,
            enable_enriched_texts=True,
            enable_reranking=False,
            full_context=True,
        )

        # Verify field access works as expected for function delegation
        assert settings.top_k == 10  # maps to k
        assert settings.top_k_reranker == 5  # maps to k_reranker
        assert settings.relevance_threshold == 0.7  # maps to r
        assert settings.hybrid_bm25_weight == 0.3
        assert settings.enable_enriched_texts is True
        assert settings.enable_reranking is False
        assert settings.full_context is True
