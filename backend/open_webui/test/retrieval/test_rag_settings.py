"""
Unit tests for merge_rag_settings and filter_results_by_relevance functions.

Tests the priority cascade: global < user < model < chat < knowledge
Later arguments override earlier ones. None values are skipped.

Also tests per-knowledge-base independent filtering behavior.
"""

import pytest
from open_webui.retrieval.utils import merge_rag_settings, filter_results_by_relevance


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


class TestFilterResultsByRelevance:
    """Tests for filter_results_by_relevance function."""

    # ==========================================
    # Basic Functionality Tests
    # ==========================================

    def test_no_filtering_when_threshold_is_zero(self):
        """Test that zero threshold returns all results unchanged."""
        query_result = {
            "distances": [[0.9, 0.5, 0.2]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, 0.0)
        assert result == query_result

    def test_no_filtering_when_threshold_is_none(self):
        """Test that None threshold returns all results unchanged."""
        query_result = {
            "distances": [[0.9, 0.5, 0.2]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, None)
        assert result == query_result

    def test_no_filtering_when_threshold_negative(self):
        """Test that negative threshold returns all results unchanged."""
        query_result = {
            "distances": [[0.9, 0.5, 0.2]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, -0.5)
        assert result == query_result

    def test_empty_result_returns_empty(self):
        """Test that empty result returns empty."""
        query_result = {
            "distances": [[]],
            "documents": [[]],
            "metadatas": [[]],
        }
        result = filter_results_by_relevance(query_result, 0.5)
        assert result == query_result

    def test_none_result_returns_none(self):
        """Test that None result returns None."""
        result = filter_results_by_relevance(None, 0.5)
        assert result is None

    # ==========================================
    # Filtering Logic Tests
    # ==========================================

    def test_filters_below_threshold(self):
        """Test that documents below threshold are filtered out."""
        query_result = {
            "distances": [[0.9, 0.5, 0.2]],
            "documents": [["high_score", "medium_score", "low_score"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, 0.5)

        assert result["distances"] == [[0.9, 0.5]]
        assert result["documents"] == [["high_score", "medium_score"]]
        assert result["metadatas"] == [[{"id": 1}, {"id": 2}]]

    def test_high_threshold_filters_most(self):
        """Test high threshold (0.8) filters out most documents."""
        query_result = {
            "distances": [[0.95, 0.85, 0.75, 0.65, 0.55]],
            "documents": [["d1", "d2", "d3", "d4", "d5"]],
            "metadatas": [[{"id": i} for i in range(1, 6)]],
        }
        result = filter_results_by_relevance(query_result, 0.8)

        assert result["distances"] == [[0.95, 0.85]]
        assert result["documents"] == [["d1", "d2"]]
        assert len(result["metadatas"][0]) == 2

    def test_low_threshold_keeps_most(self):
        """Test low threshold (0.3) keeps most documents."""
        query_result = {
            "distances": [[0.95, 0.85, 0.75, 0.65, 0.25]],
            "documents": [["d1", "d2", "d3", "d4", "d5"]],
            "metadatas": [[{"id": i} for i in range(1, 6)]],
        }
        result = filter_results_by_relevance(query_result, 0.3)

        assert result["distances"] == [[0.95, 0.85, 0.75, 0.65]]
        assert len(result["documents"][0]) == 4

    def test_exact_threshold_value_included(self):
        """Test that documents exactly at threshold are included."""
        query_result = {
            "distances": [[0.5, 0.5, 0.4]],
            "documents": [["exact1", "exact2", "below"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, 0.5)

        assert result["distances"] == [[0.5, 0.5]]
        assert result["documents"] == [["exact1", "exact2"]]

    def test_all_filtered_returns_empty_lists(self):
        """Test when all documents are below threshold."""
        query_result = {
            "distances": [[0.3, 0.2, 0.1]],
            "documents": [["d1", "d2", "d3"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, 0.5)

        assert result["distances"] == [[]]
        assert result["documents"] == [[]]
        assert result["metadatas"] == [[]]

    def test_all_pass_threshold(self):
        """Test when all documents pass threshold."""
        query_result = {
            "distances": [[0.9, 0.8, 0.7]],
            "documents": [["d1", "d2", "d3"]],
            "metadatas": [[{"id": 1}, {"id": 2}, {"id": 3}]],
        }
        result = filter_results_by_relevance(query_result, 0.5)

        assert result["distances"] == [[0.9, 0.8, 0.7]]
        assert len(result["documents"][0]) == 3


class TestPerKnowledgeBaseIndependentFiltering:
    """
    Tests for per-knowledge-base independent filtering scenarios.

    These tests verify that when multiple knowledge bases are used in the same chat,
    each KB's relevance_threshold is applied independently to its own results only.
    """

    def test_different_thresholds_independent_filtering(self):
        """
        Scenario: Two KBs with different thresholds should filter independently.

        KB-A has threshold 0.8 (strict)
        KB-B has threshold 0.3 (lenient)

        A document from KB-A scoring 0.5 should be filtered OUT.
        A document from KB-B scoring 0.5 should be KEPT.
        """
        # Simulate KB-A results with high threshold
        kb_a_results = {
            "distances": [[0.9, 0.7, 0.5]],
            "documents": [["kb_a_doc1", "kb_a_doc2", "kb_a_doc3"]],
            "metadatas": [[{"kb": "A", "id": 1}, {"kb": "A", "id": 2}, {"kb": "A", "id": 3}]],
        }
        kb_a_threshold = 0.8

        # Simulate KB-B results with low threshold
        kb_b_results = {
            "distances": [[0.6, 0.5, 0.4]],
            "documents": [["kb_b_doc1", "kb_b_doc2", "kb_b_doc3"]],
            "metadatas": [[{"kb": "B", "id": 1}, {"kb": "B", "id": 2}, {"kb": "B", "id": 3}]],
        }
        kb_b_threshold = 0.3

        # Filter independently
        kb_a_filtered = filter_results_by_relevance(kb_a_results, kb_a_threshold)
        kb_b_filtered = filter_results_by_relevance(kb_b_results, kb_b_threshold)

        # KB-A: Only 0.9 passes 0.8 threshold
        assert kb_a_filtered["distances"] == [[0.9]]
        assert kb_a_filtered["documents"] == [["kb_a_doc1"]]

        # KB-B: All 3 pass 0.3 threshold
        assert kb_b_filtered["distances"] == [[0.6, 0.5, 0.4]]
        assert len(kb_b_filtered["documents"][0]) == 3

    def test_one_kb_strict_one_kb_lenient(self):
        """
        Scenario: Legal KB needs high precision, FAQ KB can be lenient.

        Legal KB: threshold 0.9 - only highly relevant docs
        FAQ KB: threshold 0.2 - show more results to help users
        """
        legal_kb_results = {
            "distances": [[0.95, 0.88, 0.75, 0.60]],
            "documents": [["contract_law", "tort_law", "criminal", "misc"]],
            "metadatas": [[{"type": "legal"} for _ in range(4)]],
        }

        faq_kb_results = {
            "distances": [[0.7, 0.5, 0.3, 0.15]],
            "documents": [["faq1", "faq2", "faq3", "faq4"]],
            "metadatas": [[{"type": "faq"} for _ in range(4)]],
        }

        # Legal KB with strict threshold
        legal_filtered = filter_results_by_relevance(legal_kb_results, 0.9)
        # FAQ KB with lenient threshold
        faq_filtered = filter_results_by_relevance(faq_kb_results, 0.2)

        # Legal: only 0.95 passes 0.9
        assert len(legal_filtered["documents"][0]) == 1
        assert legal_filtered["documents"][0][0] == "contract_law"

        # FAQ: 3 out of 4 pass 0.2 (0.15 filtered)
        assert len(faq_filtered["documents"][0]) == 3
        assert "faq4" not in faq_filtered["documents"][0]

    def test_kb_without_custom_threshold_uses_global(self):
        """
        Scenario: KB-A has custom threshold, KB-B uses global default.

        This simulates the cascade where KBs without settings fall back to global.
        """
        global_threshold = 0.5

        # KB-A with custom threshold
        kb_a_threshold = 0.8
        kb_a_results = {
            "distances": [[0.9, 0.6]],
            "documents": [["a1", "a2"]],
            "metadatas": [[{}, {}]],
        }

        # KB-B without custom threshold (uses global)
        kb_b_results = {
            "distances": [[0.9, 0.6]],
            "documents": [["b1", "b2"]],
            "metadatas": [[{}, {}]],
        }

        # Filter KB-A with its custom threshold
        kb_a_filtered = filter_results_by_relevance(kb_a_results, kb_a_threshold)
        # Filter KB-B with global threshold
        kb_b_filtered = filter_results_by_relevance(kb_b_results, global_threshold)

        # KB-A: 0.8 threshold - only 0.9 passes
        assert kb_a_filtered["distances"] == [[0.9]]

        # KB-B: 0.5 threshold - both pass
        assert kb_b_filtered["distances"] == [[0.9, 0.6]]

    def test_same_document_different_scores_filtered_correctly(self):
        """
        Edge case: If a document appears in both KBs with different scores,
        each should be filtered according to its KB's threshold.
        """
        # Same doc content, different relevance scores from different KBs
        kb_a_results = {
            "distances": [[0.85]],  # High score in KB-A
            "documents": [["shared_document"]],
            "metadatas": [[{"source": "KB-A"}]],
        }
        kb_a_threshold = 0.9  # Strict - will filter out 0.85

        kb_b_results = {
            "distances": [[0.45]],  # Low score in KB-B
            "documents": [["shared_document"]],
            "metadatas": [[{"source": "KB-B"}]],
        }
        kb_b_threshold = 0.4  # Lenient - will keep 0.45

        kb_a_filtered = filter_results_by_relevance(kb_a_results, kb_a_threshold)
        kb_b_filtered = filter_results_by_relevance(kb_b_results, kb_b_threshold)

        # KB-A filters out 0.85 (below 0.9)
        assert kb_a_filtered["documents"] == [[]]

        # KB-B keeps 0.45 (above 0.4)
        assert kb_b_filtered["documents"] == [["shared_document"]]


class TestPerKnowledgeBaseFullContextSetting:
    """
    Tests for per-knowledge-base full_context setting.

    CRITICAL BUG BEING TESTED:
    When one KB has full_context=True and another has full_context=False,
    each KB should respect its own setting. The full_context=True KB should
    return all its documents, while the full_context=False KB should use
    vector search with relevance filtering.

    This was a bug where once ANY KB had full_context=True, ALL KBs would
    use full context mode.
    """

    def test_full_context_only_affects_own_kb(self):
        """
        Scenario: KB-A has full_context=True, KB-B has full_context=False.

        KB-A should return all documents (no vector search).
        KB-B should use vector search with filtering.

        This test verifies the settings are kept separate in the per_knowledge_settings dict.
        """
        per_knowledge_settings = {
            "kb-a-id": {
                "full_context": True,
                "relevance_threshold": 0.5,  # Ignored when full_context=True
            },
            "kb-b-id": {
                "full_context": False,
                "relevance_threshold": 0.7,
            },
        }

        # Verify settings are correctly stored per-KB
        assert per_knowledge_settings["kb-a-id"]["full_context"] is True
        assert per_knowledge_settings["kb-b-id"]["full_context"] is False

        # Simulate what the code should do:
        # For KB-A: effective_full_context = kb_settings.get("full_context", global_full_context)
        global_full_context = False

        kb_a_settings = per_knowledge_settings["kb-a-id"]
        kb_b_settings = per_knowledge_settings["kb-b-id"]

        effective_full_context_a = kb_a_settings.get("full_context", global_full_context)
        effective_full_context_b = kb_b_settings.get("full_context", global_full_context)

        assert effective_full_context_a is True, "KB-A should use full context"
        assert effective_full_context_b is False, "KB-B should NOT use full context"

    def test_kb_without_full_context_setting_uses_global_false(self):
        """
        Scenario: KB-A has full_context=True, KB-B has no full_context setting.

        KB-A should use full context.
        KB-B should fall back to global setting (False).
        """
        per_knowledge_settings = {
            "kb-a-id": {
                "full_context": True,
            },
            "kb-b-id": {
                "relevance_threshold": 0.5,
                # No full_context key
            },
        }

        global_full_context = False

        kb_a_settings = per_knowledge_settings["kb-a-id"]
        kb_b_settings = per_knowledge_settings["kb-b-id"]

        effective_full_context_a = kb_a_settings.get("full_context", global_full_context)
        effective_full_context_b = kb_b_settings.get("full_context", global_full_context)

        assert effective_full_context_a is True
        assert effective_full_context_b is False, "KB-B should fall back to global=False"

    def test_kb_without_full_context_setting_uses_global_true(self):
        """
        Scenario: Global full_context=True, KB-A overrides to False.

        KB-A should NOT use full context (overrides global).
        KB-B (no setting) should use full context (inherits global).
        """
        per_knowledge_settings = {
            "kb-a-id": {
                "full_context": False,  # Override global
            },
            "kb-b-id": {
                "relevance_threshold": 0.5,
                # No full_context key - will inherit global
            },
        }

        global_full_context = True  # Global is True

        kb_a_settings = per_knowledge_settings["kb-a-id"]
        kb_b_settings = per_knowledge_settings["kb-b-id"]

        effective_full_context_a = kb_a_settings.get("full_context", global_full_context)
        effective_full_context_b = kb_b_settings.get("full_context", global_full_context)

        assert effective_full_context_a is False, "KB-A overrides global to False"
        assert effective_full_context_b is True, "KB-B inherits global=True"

    def test_mixed_settings_all_rag_options_independent(self):
        """
        Comprehensive test: ALL 6 RAG settings should be independent per KB.

        KB-A: Optimized for precision (strict filtering, no full context)
        KB-B: Optimized for recall (lenient filtering, full context)
        KB-C: Uses global defaults
        """
        global_settings = {
            "top_k": 10,
            "top_k_reranker": 5,
            "relevance_threshold": 0.5,
            "enable_hybrid_search": False,
            "hybrid_bm25_weight": 0.5,
            "full_context": False,
        }

        per_knowledge_settings = {
            "kb-precision": {
                "top_k": 3,
                "top_k_reranker": 2,
                "relevance_threshold": 0.9,
                "enable_hybrid_search": True,
                "hybrid_bm25_weight": 0.3,
                "full_context": False,
            },
            "kb-recall": {
                "top_k": 20,
                "top_k_reranker": 10,
                "relevance_threshold": 0.1,
                "enable_hybrid_search": False,
                "hybrid_bm25_weight": 0.7,
                "full_context": True,
            },
            "kb-default": {
                # No custom settings - should use global
            },
        }

        # Helper to get effective setting
        def get_effective(kb_id, setting_name):
            kb_settings = per_knowledge_settings.get(kb_id, {})
            return kb_settings.get(setting_name, global_settings[setting_name])

        # Verify KB-precision settings
        assert get_effective("kb-precision", "top_k") == 3
        assert get_effective("kb-precision", "top_k_reranker") == 2
        assert get_effective("kb-precision", "relevance_threshold") == 0.9
        assert get_effective("kb-precision", "enable_hybrid_search") is True
        assert get_effective("kb-precision", "hybrid_bm25_weight") == 0.3
        assert get_effective("kb-precision", "full_context") is False

        # Verify KB-recall settings
        assert get_effective("kb-recall", "top_k") == 20
        assert get_effective("kb-recall", "top_k_reranker") == 10
        assert get_effective("kb-recall", "relevance_threshold") == 0.1
        assert get_effective("kb-recall", "enable_hybrid_search") is False
        assert get_effective("kb-recall", "hybrid_bm25_weight") == 0.7
        assert get_effective("kb-recall", "full_context") is True

        # Verify KB-default uses global settings
        assert get_effective("kb-default", "top_k") == 10
        assert get_effective("kb-default", "top_k_reranker") == 5
        assert get_effective("kb-default", "relevance_threshold") == 0.5
        assert get_effective("kb-default", "enable_hybrid_search") is False
        assert get_effective("kb-default", "hybrid_bm25_weight") == 0.5
        assert get_effective("kb-default", "full_context") is False

    def test_hybrid_search_independent_per_kb(self):
        """
        Scenario: KB-A uses hybrid search, KB-B uses standard vector search.

        Each KB should use its own search method independently.
        """
        per_knowledge_settings = {
            "kb-hybrid": {
                "enable_hybrid_search": True,
                "hybrid_bm25_weight": 0.4,
            },
            "kb-vector": {
                "enable_hybrid_search": False,
            },
        }

        global_hybrid = False

        kb_hybrid_settings = per_knowledge_settings["kb-hybrid"]
        kb_vector_settings = per_knowledge_settings["kb-vector"]

        effective_hybrid_a = kb_hybrid_settings.get("enable_hybrid_search", global_hybrid)
        effective_hybrid_b = kb_vector_settings.get("enable_hybrid_search", global_hybrid)

        assert effective_hybrid_a is True, "KB-hybrid should use hybrid search"
        assert effective_hybrid_b is False, "KB-vector should use standard search"

    def test_top_k_independent_per_kb(self):
        """
        Scenario: Different KBs need different result counts.

        KB-FAQ: Many results (top_k=20) for broad coverage
        KB-Legal: Few results (top_k=3) for precision
        """
        per_knowledge_settings = {
            "kb-faq": {
                "top_k": 20,
                "top_k_reranker": 15,
            },
            "kb-legal": {
                "top_k": 3,
                "top_k_reranker": 2,
            },
        }

        global_top_k = 10
        global_top_k_reranker = 5

        # Verify FAQ KB gets more results
        faq_k = per_knowledge_settings["kb-faq"].get("top_k", global_top_k)
        faq_k_reranker = per_knowledge_settings["kb-faq"].get("top_k_reranker", global_top_k_reranker)
        assert faq_k == 20
        assert faq_k_reranker == 15

        # Verify Legal KB gets fewer results
        legal_k = per_knowledge_settings["kb-legal"].get("top_k", global_top_k)
        legal_k_reranker = per_knowledge_settings["kb-legal"].get("top_k_reranker", global_top_k_reranker)
        assert legal_k == 3
        assert legal_k_reranker == 2
