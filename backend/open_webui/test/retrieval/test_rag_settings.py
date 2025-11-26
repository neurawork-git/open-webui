"""
Unit tests for merge_rag_settings function.

Tests the priority cascade: global < user < model < chat < knowledge
Later arguments override earlier ones. None values are skipped.
"""

import pytest
from open_webui.retrieval.utils import merge_rag_settings


class TestMergeRagSettings:
    """Tests for merge_rag_settings function."""

    # ==========================================
    # Basic Functionality Tests
    # ==========================================

    def test_empty_input_returns_empty_dict(self):
        """Test that no arguments returns empty dict."""
        result = merge_rag_settings()
        assert result == {}

    def test_single_none_returns_empty_dict(self):
        """Test that a single None argument returns empty dict."""
        result = merge_rag_settings(None)
        assert result == {}

    def test_multiple_nones_return_empty_dict(self):
        """Test that multiple None arguments return empty dict."""
        result = merge_rag_settings(None, None, None)
        assert result == {}

    def test_single_dict_passes_through(self):
        """Test that a single dict is returned as-is (filtered to valid keys)."""
        settings = {
            "top_k": 5,
            "relevance_threshold": 0.7,
        }
        result = merge_rag_settings(settings)
        assert result == {"top_k": 5, "relevance_threshold": 0.7}

    def test_empty_dict_returns_empty_dict(self):
        """Test that empty dict returns empty dict."""
        result = merge_rag_settings({})
        assert result == {}

    # ==========================================
    # Key Filtering Tests
    # ==========================================

    def test_only_valid_rag_keys_included(self):
        """Test that only valid RAG keys are included in output."""
        settings = {
            "top_k": 5,
            "invalid_key": "should_be_ignored",
            "another_invalid": 123,
        }
        result = merge_rag_settings(settings)
        assert result == {"top_k": 5}
        assert "invalid_key" not in result
        assert "another_invalid" not in result

    def test_all_valid_keys_supported(self):
        """Test that all valid RAG keys are supported."""
        settings = {
            "top_k": 5,
            "top_k_reranker": 3,
            "relevance_threshold": 0.5,
            "enable_hybrid_search": True,
            "hybrid_bm25_weight": 0.3,
            "full_context": False,
        }
        result = merge_rag_settings(settings)
        assert result == settings

    # ==========================================
    # None Value Handling Tests
    # ==========================================

    def test_none_values_in_dict_are_skipped(self):
        """Test that None values within a dict are not included."""
        settings = {
            "top_k": 5,
            "relevance_threshold": None,
        }
        result = merge_rag_settings(settings)
        assert result == {"top_k": 5}
        assert "relevance_threshold" not in result

    def test_none_value_does_not_override_previous(self):
        """Test that a None value in later dict doesn't override earlier value."""
        global_settings = {"top_k": 10}
        user_settings = {"top_k": None}
        result = merge_rag_settings(global_settings, user_settings)
        assert result == {"top_k": 10}

    # ==========================================
    # Priority Cascade Tests (Core Functionality)
    # ==========================================

    def test_later_dict_overrides_earlier(self):
        """Test that later dict values override earlier ones."""
        global_settings = {"top_k": 10}
        user_settings = {"top_k": 5}
        result = merge_rag_settings(global_settings, user_settings)
        assert result == {"top_k": 5}

    def test_full_cascade_priority(self):
        """Test full cascade: global < user < model < chat < knowledge."""
        global_settings = {
            "top_k": 10,
            "relevance_threshold": 0.5,
            "enable_hybrid_search": False,
        }
        user_settings = {
            "top_k": 8,  # Override global
            "full_context": True,  # New value
        }
        model_settings = {
            "top_k": 6,  # Override user
            "top_k_reranker": 3,  # New value
        }
        chat_settings = {
            "hybrid_bm25_weight": 0.4,  # New value
        }
        knowledge_settings = {
            "top_k": 5,  # Override model (highest priority)
            "relevance_threshold": 0.8,  # Override global
        }

        result = merge_rag_settings(
            global_settings,
            user_settings,
            model_settings,
            chat_settings,
            knowledge_settings,
        )

        assert result == {
            "top_k": 5,  # From knowledge (highest priority)
            "relevance_threshold": 0.8,  # From knowledge
            "enable_hybrid_search": False,  # From global (not overridden)
            "full_context": True,  # From user
            "top_k_reranker": 3,  # From model
            "hybrid_bm25_weight": 0.4,  # From chat
        }

    def test_sparse_settings_merge_correctly(self):
        """Test that sparse settings from different levels merge correctly."""
        global_settings = {"top_k": 10}
        user_settings = {"relevance_threshold": 0.6}
        model_settings = {"enable_hybrid_search": True}

        result = merge_rag_settings(global_settings, user_settings, model_settings)

        assert result == {
            "top_k": 10,
            "relevance_threshold": 0.6,
            "enable_hybrid_search": True,
        }

    def test_none_dicts_in_middle_dont_affect_cascade(self):
        """Test that None dicts in the middle of cascade don't break it."""
        global_settings = {"top_k": 10}
        user_settings = None
        model_settings = {"top_k": 5}

        result = merge_rag_settings(global_settings, user_settings, model_settings)

        assert result == {"top_k": 5}

    # ==========================================
    # Type Handling Tests
    # ==========================================

    def test_boolean_false_is_preserved(self):
        """Test that boolean False is not treated as None/empty."""
        settings = {"enable_hybrid_search": False, "full_context": False}
        result = merge_rag_settings(settings)
        assert result == {"enable_hybrid_search": False, "full_context": False}

    def test_zero_value_is_preserved(self):
        """Test that zero values are preserved (not treated as None)."""
        settings = {"relevance_threshold": 0.0, "hybrid_bm25_weight": 0}
        result = merge_rag_settings(settings)
        assert result == {"relevance_threshold": 0.0, "hybrid_bm25_weight": 0}

    def test_boolean_override_works(self):
        """Test that boolean values can be overridden."""
        global_settings = {"enable_hybrid_search": True}
        user_settings = {"enable_hybrid_search": False}
        result = merge_rag_settings(global_settings, user_settings)
        assert result == {"enable_hybrid_search": False}

    # ==========================================
    # Edge Cases
    # ==========================================

    def test_large_number_of_settings_dicts(self):
        """Test with many settings dicts (simulating deep cascade)."""
        dicts = [{"top_k": i} for i in range(10)]
        result = merge_rag_settings(*dicts)
        assert result == {"top_k": 9}  # Last value wins

    def test_all_keys_overridden_at_each_level(self):
        """Test that all keys can be overridden at each level."""
        level1 = {
            "top_k": 1,
            "top_k_reranker": 1,
            "relevance_threshold": 0.1,
            "enable_hybrid_search": False,
            "hybrid_bm25_weight": 0.1,
            "full_context": False,
        }
        level2 = {
            "top_k": 2,
            "top_k_reranker": 2,
            "relevance_threshold": 0.2,
            "enable_hybrid_search": True,
            "hybrid_bm25_weight": 0.2,
            "full_context": True,
        }
        result = merge_rag_settings(level1, level2)
        assert result == level2

    def test_partial_override(self):
        """Test partial override - some keys change, others stay."""
        base = {
            "top_k": 10,
            "relevance_threshold": 0.5,
            "enable_hybrid_search": True,
        }
        override = {
            "top_k": 5,
            # relevance_threshold not specified - should keep base
            # enable_hybrid_search not specified - should keep base
        }
        result = merge_rag_settings(base, override)
        assert result == {
            "top_k": 5,  # Overridden
            "relevance_threshold": 0.5,  # From base
            "enable_hybrid_search": True,  # From base
        }


class TestMergeRagSettingsRealWorldScenarios:
    """Real-world scenario tests for merge_rag_settings."""

    def test_scenario_user_wants_more_results(self):
        """
        Scenario: Global is conservative (top_k=3),
        but user wants more context (top_k=10).
        """
        global_settings = {
            "top_k": 3,
            "relevance_threshold": 0.5,
        }
        user_settings = {
            "top_k": 10,
        }
        result = merge_rag_settings(global_settings, user_settings)
        assert result["top_k"] == 10
        assert result["relevance_threshold"] == 0.5

    def test_scenario_knowledge_base_needs_full_context(self):
        """
        Scenario: A specific knowledge base needs full document context,
        overriding all other retrieval settings.
        """
        global_settings = {"top_k": 5, "relevance_threshold": 0.5}
        user_settings = {"top_k": 10}
        model_settings = {"top_k": 8}
        knowledge_settings = {"full_context": True}

        result = merge_rag_settings(
            global_settings, user_settings, model_settings, knowledge_settings
        )

        assert result["full_context"] is True
        assert result["top_k"] == 8  # From model (knowledge didn't override)

    def test_scenario_model_optimized_for_precision(self):
        """
        Scenario: A specific model needs high precision (high threshold)
        but user prefers more results.
        """
        global_settings = {"top_k": 5, "relevance_threshold": 0.3}
        user_settings = {"top_k": 15}
        model_settings = {"relevance_threshold": 0.8, "top_k_reranker": 5}

        result = merge_rag_settings(global_settings, user_settings, model_settings)

        assert result == {
            "top_k": 15,  # From user
            "relevance_threshold": 0.8,  # From model
            "top_k_reranker": 5,  # From model
        }

    def test_scenario_hybrid_search_enabled_at_model_level(self):
        """
        Scenario: Hybrid search disabled globally but enabled for specific model.
        """
        global_settings = {
            "enable_hybrid_search": False,
            "top_k": 5,
        }
        model_settings = {
            "enable_hybrid_search": True,
            "hybrid_bm25_weight": 0.4,
        }

        result = merge_rag_settings(global_settings, model_settings)

        assert result["enable_hybrid_search"] is True
        assert result["hybrid_bm25_weight"] == 0.4
        assert result["top_k"] == 5

    def test_scenario_no_custom_settings_uses_global(self):
        """
        Scenario: User/Model/Knowledge have no custom settings,
        global settings are used.
        """
        global_settings = {
            "top_k": 5,
            "relevance_threshold": 0.5,
            "enable_hybrid_search": True,
        }

        result = merge_rag_settings(global_settings, None, None, {}, None)

        assert result == global_settings
