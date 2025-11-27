"""
Unit tests for BM25 tokenization function.

Tests the tokenize_for_bm25 function which handles punctuation stripping
while preserving German umlauts and internal characters.
"""

import pytest
from open_webui.retrieval.utils import tokenize_for_bm25


class TestTokenizeForBm25:
    """Tests for tokenize_for_bm25 function."""

    # ==========================================
    # Basic Punctuation Stripping
    # ==========================================

    def test_strips_trailing_comma(self):
        """Test that trailing comma is stripped from city names."""
        result = tokenize_for_bm25("Berlin, Stadt")
        assert result == ["berlin", "stadt"]

    def test_strips_trailing_period(self):
        """Test that trailing period is stripped."""
        result = tokenize_for_bm25("Ende.")
        assert result == ["ende"]

    def test_strips_leading_punctuation(self):
        """Test that leading punctuation is stripped."""
        result = tokenize_for_bm25("(Hamburg) [Munich]")
        assert result == ["hamburg", "munich"]

    def test_strips_multiple_punctuation(self):
        """Test that multiple punctuation marks are stripped."""
        result = tokenize_for_bm25("...text... !!!important!!!")
        assert result == ["text", "important"]

    def test_strips_quotes(self):
        """Test that quotes are stripped."""
        result = tokenize_for_bm25('"quoted" \'text\'')
        assert result == ["quoted", "text"]

    # ==========================================
    # German Language Support
    # ==========================================

    def test_preserves_german_umlauts(self):
        """Test that German umlauts are preserved."""
        result = tokenize_for_bm25("München Düsseldorf Köln")
        assert result == ["münchen", "düsseldorf", "köln"]

    def test_preserves_eszett(self):
        """Test that German ß is preserved."""
        result = tokenize_for_bm25("Straße Größe")
        assert result == ["straße", "größe"]

    def test_bevoelkerung_query(self):
        """Test the real-world query case: Bevölkerung Leipzig."""
        result = tokenize_for_bm25("Bevölkerung Leipzig")
        assert result == ["bevölkerung", "leipzig"]

    def test_german_table_header(self):
        """Test tokenization of actual German table header."""
        text = "| Bevölkerung auf Grundlage ZENSUS2011 |"
        result = tokenize_for_bm25(text)
        assert "bevölkerung" in result
        assert "grundlage" in result
        assert "zensus2011" in result

    # ==========================================
    # Numbers and Mixed Content
    # ==========================================

    def test_preserves_plain_numbers(self):
        """Test that plain numbers are preserved."""
        result = tokenize_for_bm25("10178 12345")
        assert result == ["10178", "12345"]

    def test_preserves_decimal_numbers(self):
        """Test that decimal numbers with internal periods are preserved."""
        result = tokenize_for_bm25("891.12 310.7")
        assert result == ["891.12", "310.7"]

    def test_table_row_mixed_content(self):
        """Test tokenization of actual table row content."""
        text = "| 8 | 14 | 7 | 13 | Leipzig, Stadt | 04109 | 297.8 |"
        result = tokenize_for_bm25(text)
        assert "8" in result
        assert "leipzig" in result
        assert "stadt" in result
        assert "04109" in result
        assert "297.8" in result

    # ==========================================
    # Edge Cases
    # ==========================================

    def test_empty_string_returns_empty_list(self):
        """Test that empty string returns empty list."""
        result = tokenize_for_bm25("")
        assert result == []

    def test_only_punctuation_returns_empty_list(self):
        """Test that string with only punctuation returns empty list."""
        result = tokenize_for_bm25("... !!! ???")
        assert result == []

    def test_only_whitespace_returns_empty_list(self):
        """Test that string with only whitespace returns empty list."""
        result = tokenize_for_bm25("   \t\n   ")
        assert result == []

    def test_multiple_spaces_handled(self):
        """Test that multiple spaces don't create empty tokens."""
        result = tokenize_for_bm25("word1    word2     word3")
        assert result == ["word1", "word2", "word3"]

    def test_newlines_in_text(self):
        """Test that newlines act as separators."""
        result = tokenize_for_bm25("line1\nline2\nline3")
        assert result == ["line1", "line2", "line3"]

    # ==========================================
    # Internal Characters Preserved
    # ==========================================

    def test_preserves_internal_hyphen(self):
        """Test that internal hyphens are preserved."""
        result = tokenize_for_bm25("Baden-Württemberg")
        assert result == ["baden-württemberg"]

    def test_preserves_internal_period_in_numbers(self):
        """Test that internal periods in numbers are preserved."""
        result = tokenize_for_bm25("3.782.202")
        # Note: This is European number format (3,782,202)
        assert result == ["3.782.202"]

    def test_preserves_underscore(self):
        """Test that underscores are preserved (common in identifiers)."""
        result = tokenize_for_bm25("file_name some_variable")
        assert result == ["file_name", "some_variable"]

    # ==========================================
    # Case Conversion
    # ==========================================

    def test_converts_to_lowercase(self):
        """Test that all text is converted to lowercase."""
        result = tokenize_for_bm25("BERLIN Berlin berlin")
        assert result == ["berlin", "berlin", "berlin"]

    def test_mixed_case_german(self):
        """Test case conversion with German umlauts."""
        result = tokenize_for_bm25("MÜNCHEN München münchen")
        assert result == ["münchen", "münchen", "münchen"]

    # ==========================================
    # Real-World Test Case from Investigation
    # ==========================================

    def test_actual_chunk_matches_query(self):
        """
        Test the actual use case from the hybrid search investigation:
        Query 'berlin' should match a document containing 'Berlin, Stadt'
        """
        # Simulate the chunk content
        chunk = "| 8 | 14 | 7 | 13 | 0000 | 000 | Leipzig, Stadt | 04109 | 297.8 | 619879 |"
        query = "Bevölkerung Leipzig 2023"

        chunk_tokens = tokenize_for_bm25(chunk)
        query_tokens = tokenize_for_bm25(query)

        # The key assertion: 'leipzig' should be in both
        assert "leipzig" in chunk_tokens, f"'leipzig' not found in chunk tokens: {chunk_tokens}"
        assert "leipzig" in query_tokens, f"'leipzig' not found in query tokens: {query_tokens}"

        # Verify no comma attached
        assert "leipzig," not in chunk_tokens, "Comma should be stripped from 'Leipzig,'"

    def test_berlin_chunk_matches_berlin_query(self):
        """
        Test that Berlin chunk matches Berlin query (the original bug).
        """
        chunk = "| 1 | 11 | 0 | 00 | 0000 | 000 | Berlin, Stadt | 10178 | 891.12 | 3782202 |"
        query = "aktuelle Bevölkerungszahl Berlin 2025"

        chunk_tokens = tokenize_for_bm25(chunk)
        query_tokens = tokenize_for_bm25(query)

        # Berlin should match
        assert "berlin" in chunk_tokens
        assert "berlin" in query_tokens

        # Common tokens should exist
        common = set(chunk_tokens) & set(query_tokens)
        assert "berlin" in common, f"Expected 'berlin' in common tokens, got: {common}"
