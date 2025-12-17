"""
Integration tests for BM25 keyword highlighting.

These tests verify that BM25 matched keywords:
1. Are properly extracted and added to metadata
2. Survive the merge_and_sort_query_results deduplication
3. Are properly passed through the full retrieval pipeline
"""

import pytest
import hashlib
from open_webui.retrieval.utils import (
    extract_matched_keywords,
    merge_and_sort_query_results,
    filter_results_by_relevance,
)


class TestMergePreservesKeywords:
    """Tests for keyword preservation during merge_and_sort_query_results."""

    def test_keywords_preserved_when_first_result_has_higher_score(self):
        """When hybrid result (with keywords) has higher score, keywords should be kept."""
        doc_content = "Berlin is a city with great population."

        # First result: hybrid search with keywords and higher score
        hybrid_result = {
            "distances": [[0.85]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
                "bm25_matched_keywords": ["berlin", "population"],
            }]],
        }

        # Second result: vector search without keywords and lower score
        vector_result = {
            "distances": [[0.75]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
            }]],
        }

        merged = merge_and_sort_query_results([hybrid_result, vector_result], k=5)

        # Should have 1 unique document
        assert len(merged["documents"][0]) == 1

        # Keywords should be preserved (hybrid had higher score)
        metadata = merged["metadatas"][0][0]
        assert "bm25_matched_keywords" in metadata
        assert metadata["bm25_matched_keywords"] == ["berlin", "population"]

    def test_keywords_preserved_when_vector_has_higher_score(self):
        """
        Keywords should be preserved even when vector result has higher score.

        The merge function should merge metadata when deduplicating, preserving
        bm25_matched_keywords from the hybrid search result even if the vector
        search result has a higher score.
        """
        doc_content = "Berlin is a city with great population."

        # First result: hybrid search with keywords but LOWER score
        hybrid_result = {
            "distances": [[0.75]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
                "bm25_matched_keywords": ["berlin", "population"],
            }]],
        }

        # Second result: vector search without keywords but HIGHER score
        vector_result = {
            "distances": [[0.85]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
            }]],
        }

        merged = merge_and_sort_query_results([hybrid_result, vector_result], k=5)

        # Should have 1 unique document
        assert len(merged["documents"][0]) == 1

        # Score should be the higher one (from vector search)
        assert merged["distances"][0][0] == 0.85

        # Keywords should be preserved from hybrid search result
        metadata = merged["metadatas"][0][0]
        assert "bm25_matched_keywords" in metadata
        assert metadata["bm25_matched_keywords"] == ["berlin", "population"]

    def test_keywords_preserved_with_vector_first_hybrid_second(self):
        """
        Keywords should be preserved when vector result comes first (higher score),
        then hybrid result comes second (with keywords but lower score).

        This tests the case where the order of results is reversed.
        """
        doc_content = "Berlin is a city with great population."

        # Vector search without keywords (higher score) - comes first
        vector_result = {
            "distances": [[0.90]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
            }]],
        }

        # Hybrid search with keywords (lower score) - comes second
        hybrid_result = {
            "distances": [[0.70]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
                "bm25_matched_keywords": ["berlin", "population"],
            }]],
        }

        merged = merge_and_sort_query_results([vector_result, hybrid_result], k=5)

        metadata = merged["metadatas"][0][0]

        # Score should be the higher one
        assert merged["distances"][0][0] == 0.90

        # Keywords should be preserved from hybrid result even though it came second
        assert "bm25_matched_keywords" in metadata
        assert metadata["bm25_matched_keywords"] == ["berlin", "population"]

    def test_multiple_documents_with_mixed_keywords(self):
        """Test merging multiple documents where some have keywords and some don't."""
        doc1 = "Berlin is the capital of Germany."
        doc2 = "Munich is in Bavaria."
        doc3 = "Hamburg is a port city."

        # Hybrid result with keywords for doc1 and doc3
        hybrid_result = {
            "distances": [[0.80, 0.60]],
            "documents": [[doc1, doc3]],
            "metadatas": [[
                {"source": "a.txt", "bm25_matched_keywords": ["berlin", "capital"]},
                {"source": "c.txt", "bm25_matched_keywords": ["hamburg", "port"]},
            ]],
        }

        # Vector result with doc2 (no keywords)
        vector_result = {
            "distances": [[0.70]],
            "documents": [[doc2]],
            "metadatas": [[{"source": "b.txt"}]],
        }

        merged = merge_and_sort_query_results([hybrid_result, vector_result], k=5)

        # Should have all 3 documents
        assert len(merged["documents"][0]) == 3

        # Check that non-overlapping documents preserve their keywords
        for i, meta in enumerate(merged["metadatas"][0]):
            doc = merged["documents"][0][i]
            if "Berlin" in doc:
                assert "bm25_matched_keywords" in meta
            elif "Munich" in doc:
                assert "bm25_matched_keywords" not in meta
            elif "Hamburg" in doc:
                assert "bm25_matched_keywords" in meta

    def test_empty_keywords_list_preserved(self):
        """Test that empty keywords list is preserved (not removed)."""
        doc_content = "This document has no matching keywords."

        result = {
            "distances": [[0.80]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "test.txt",
                "bm25_matched_keywords": [],  # Empty list, but present
            }]],
        }

        merged = merge_and_sort_query_results([result], k=5)

        metadata = merged["metadatas"][0][0]
        assert "bm25_matched_keywords" in metadata
        assert metadata["bm25_matched_keywords"] == []


class TestExtractMatchedKeywordsIntegration:
    """Integration tests for keyword extraction with real-world content."""

    def test_german_city_statistics_table(self):
        """Test keyword extraction from the German city statistics table."""
        query = "Bevölkerung Leipzig"
        document = """| Leipzig, Stadt | 04109 | 297.8 | 619879 | 305443 | 314436 | 2082 |
| Dresden, Stadt | 01067 | 328.48 | 566222 | 281215 | 285007 | 1724 |"""

        keywords = extract_matched_keywords(query, document)

        assert "bevölkerung" in keywords or "leipzig" in keywords
        assert len(keywords) >= 1

    def test_keywords_extraction_with_punctuation(self):
        """Test that punctuation doesn't prevent keyword matches."""
        query = "Berlin population"
        document = "Berlin, (population: 3.7M) is Germany's capital city."

        keywords = extract_matched_keywords(query, document)

        assert "berlin" in keywords
        assert "population" in keywords

    def test_keywords_extraction_preserves_order(self):
        """Test that keywords are returned in query order."""
        query = "alpha beta gamma"
        document = "The gamma and alpha values are important."

        keywords = extract_matched_keywords(query, document)

        # Should be in query order: alpha first, then gamma
        assert keywords == ["alpha", "gamma"]

    def test_keywords_extraction_no_duplicates(self):
        """Test that duplicate query terms don't cause duplicate results."""
        query = "Berlin Berlin city city"
        document = "Berlin is a great city."

        keywords = extract_matched_keywords(query, document)

        # Should have unique keywords only
        assert keywords.count("berlin") == 1
        assert keywords.count("city") == 1


class TestFilterPreservesKeywords:
    """Test that filter_results_by_relevance preserves keywords."""

    def test_keywords_preserved_after_filtering(self):
        """Keywords should survive relevance filtering."""
        result = {
            "distances": [[0.90, 0.50, 0.30]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[
                {"source": "a.txt", "bm25_matched_keywords": ["keyword1"]},
                {"source": "b.txt", "bm25_matched_keywords": ["keyword2"]},
                {"source": "c.txt", "bm25_matched_keywords": ["keyword3"]},
            ]],
        }

        # Filter to keep only docs with score >= 0.5
        filtered = filter_results_by_relevance(result, 0.5)

        # Should have 2 documents
        assert len(filtered["documents"][0]) == 2

        # Keywords should be preserved
        for meta in filtered["metadatas"][0]:
            assert "bm25_matched_keywords" in meta


class TestKeywordsInFullPipeline:
    """
    Integration tests simulating the full retrieval pipeline.

    These tests verify that keywords flow correctly through:
    1. Hybrid search (where keywords are added)
    2. Merge results (where duplicates are removed)
    3. Filter results (where low-score docs are removed)
    """

    def test_full_pipeline_simulation(self):
        """Simulate full pipeline from hybrid search to final results."""
        # Simulate what query_doc_with_hybrid_search returns
        doc1 = "Berlin is the capital with large population."
        doc2 = "Munich has the highest density."
        doc3 = "Hamburg is a major port city."

        # Hybrid search result (with keywords)
        hybrid_search_result = {
            "distances": [[0.75, 0.65, 0.55]],
            "documents": [[doc1, doc2, doc3]],
            "metadatas": [[
                {"source": "cities.txt", "bm25_matched_keywords": ["berlin", "capital", "population"]},
                {"source": "cities.txt", "bm25_matched_keywords": ["munich", "density"]},
                {"source": "cities.txt", "bm25_matched_keywords": ["hamburg", "port"]},
            ]],
        }

        # Step 1: Merge (simulating multiple knowledge bases)
        merged = merge_and_sort_query_results([hybrid_search_result], k=10)

        # Step 2: Filter by relevance
        filtered = filter_results_by_relevance(merged, 0.5)

        # Verify keywords survived the pipeline
        assert len(filtered["documents"][0]) == 3
        for meta in filtered["metadatas"][0]:
            assert "bm25_matched_keywords" in meta

    def test_pipeline_with_overlapping_results_from_multiple_kbs(self):
        """Test pipeline when same doc appears in multiple knowledge base results."""
        doc_content = "Leipzig is a city in Saxony."

        # KB1: Hybrid search with keywords
        kb1_result = {
            "distances": [[0.70]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "kb1.txt",
                "bm25_matched_keywords": ["leipzig", "saxony"],
                "file_id": "file1",
            }]],
        }

        # KB2: Also has the same document (maybe different ingestion)
        kb2_result = {
            "distances": [[0.65]],
            "documents": [[doc_content]],
            "metadatas": [[{
                "source": "kb2.txt",
                "file_id": "file2",
            }]],
        }

        merged = merge_and_sort_query_results([kb1_result, kb2_result], k=5)

        # Should deduplicate to 1 document
        assert len(merged["documents"][0]) == 1

        # Keywords should be preserved (kb1 had higher score)
        metadata = merged["metadatas"][0][0]
        assert "bm25_matched_keywords" in metadata
        assert "leipzig" in metadata["bm25_matched_keywords"]


class TestScorePreservation:
    """Tests for score/distance preservation and ordering."""

    def test_bm25_weight_1_uses_bm25_scores(self):
        """
        When BM25 weight is 1.0, results should use BM25 scoring.

        This test verifies that the merge function doesn't inadvertently
        replace BM25 scores with vector search scores.
        """
        doc1 = "Berlin population statistics 2023"
        doc2 = "General information about cities"

        # Hybrid search with BM25 weight=1.0 (should have high scores for keyword matches)
        bm25_only_result = {
            "distances": [[0.95, 0.20]],  # doc1 has high BM25 score (keyword match)
            "documents": [[doc1, doc2]],
            "metadatas": [[
                {"source": "a.txt", "bm25_matched_keywords": ["berlin", "population"]},
                {"source": "b.txt", "bm25_matched_keywords": []},
            ]],
        }

        merged = merge_and_sort_query_results([bm25_only_result], k=5)

        # Scores should be preserved
        assert merged["distances"][0][0] == 0.95
        assert merged["distances"][0][1] == 0.20

        # Order should be by score descending
        assert merged["documents"][0][0] == doc1
        assert merged["documents"][0][1] == doc2

    def test_highest_score_wins_in_merge(self):
        """When same doc appears with different scores, highest should win."""
        doc_content = "Test document content"

        result1 = {
            "distances": [[0.60]],
            "documents": [[doc_content]],
            "metadatas": [[{"source": "a.txt"}]],
        }

        result2 = {
            "distances": [[0.80]],
            "documents": [[doc_content]],
            "metadatas": [[{"source": "b.txt"}]],
        }

        result3 = {
            "distances": [[0.70]],
            "documents": [[doc_content]],
            "metadatas": [[{"source": "c.txt"}]],
        }

        merged = merge_and_sort_query_results([result1, result2, result3], k=5)

        assert len(merged["documents"][0]) == 1
        assert merged["distances"][0][0] == 0.80  # Highest score wins


class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_empty_results_handling(self):
        """Test handling of empty results."""
        empty_result = {
            "distances": [[]],
            "documents": [[]],
            "metadatas": [[]],
        }

        merged = merge_and_sort_query_results([empty_result], k=5)

        assert merged["documents"][0] == []
        assert merged["metadatas"][0] == []
        assert merged["distances"][0] == []

    def test_none_metadata_fields(self):
        """Test handling when metadata has None values."""
        result = {
            "distances": [[0.80]],
            "documents": [["Test content"]],
            "metadatas": [[{
                "source": "test.txt",
                "bm25_matched_keywords": None,
            }]],
        }

        merged = merge_and_sort_query_results([result], k=5)

        # Should handle None gracefully
        metadata = merged["metadatas"][0][0]
        assert metadata.get("bm25_matched_keywords") is None

    def test_large_k_value(self):
        """Test that k larger than result count works correctly."""
        result = {
            "distances": [[0.80, 0.70]],
            "documents": [["doc1", "doc2"]],
            "metadatas": [[
                {"source": "a.txt", "bm25_matched_keywords": ["key1"]},
                {"source": "b.txt", "bm25_matched_keywords": ["key2"]},
            ]],
        }

        # k=100 but only 2 results
        merged = merge_and_sort_query_results([result], k=100)

        assert len(merged["documents"][0]) == 2
        for meta in merged["metadatas"][0]:
            assert "bm25_matched_keywords" in meta

    def test_special_characters_in_keywords(self):
        """Test keywords with special characters are handled."""
        query = "C++ programming"
        document = "C++ is a powerful programming language."

        keywords = extract_matched_keywords(query, document)

        # At minimum, 'programming' should match
        assert "programming" in keywords

    def test_none_distances_pure_bm25(self):
        """Test handling of None distances from pure BM25 search (bm25_weight=1)."""
        # When BM25 weight is 1.0, there are no vector distances, so distances are None
        result = {
            "distances": [[None, None, None]],
            "documents": [["doc1", "doc2", "doc3"]],
            "metadatas": [[
                {"source": "a.txt", "bm25_matched_keywords": ["keyword1"]},
                {"source": "b.txt", "bm25_matched_keywords": ["keyword2"]},
                {"source": "c.txt", "bm25_matched_keywords": ["keyword3"]},
            ]],
        }

        # Should not raise TypeError when comparing None values
        merged = merge_and_sort_query_results([result], k=5)

        assert len(merged["documents"][0]) == 3
        # Keywords should be preserved
        for meta in merged["metadatas"][0]:
            assert "bm25_matched_keywords" in meta

    def test_mixed_none_and_numeric_distances(self):
        """Test deduplication when some distances are None and some are numeric."""
        doc_content = "Same document content"

        # Result with numeric distance
        result1 = {
            "distances": [[0.75]],
            "documents": [[doc_content]],
            "metadatas": [[{"source": "a.txt"}]],
        }

        # Result with None distance but with keywords
        result2 = {
            "distances": [[None]],
            "documents": [[doc_content]],
            "metadatas": [[{"source": "b.txt", "bm25_matched_keywords": ["keyword"]}]],
        }

        merged = merge_and_sort_query_results([result1, result2], k=5)

        # Should deduplicate to 1 document
        assert len(merged["documents"][0]) == 1

        # The numeric distance should win (0.75 > 0 which is None's default)
        assert merged["distances"][0][0] == 0.75

        # But keywords should be preserved from the None-distance result
        assert "bm25_matched_keywords" in merged["metadatas"][0][0]
