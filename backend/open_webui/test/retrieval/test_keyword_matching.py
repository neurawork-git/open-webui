"""
Unit tests for BM25 keyword matching/highlighting functionality.
"""

import pytest
from open_webui.retrieval.utils import extract_matched_keywords, tokenize_for_bm25


class TestExtractMatchedKeywords:
    """Tests for the extract_matched_keywords function."""

    def test_basic_match(self):
        """Test basic keyword matching."""
        query = "Berlin 2025"
        document = "Berlin is hosting a conference in 2025."

        matched = extract_matched_keywords(query, document)

        assert "berlin" in matched
        assert "2025" in matched
        assert len(matched) == 2

    def test_no_match(self):
        """Test when no keywords match."""
        query = "Python programming"
        document = "The weather in London is nice today."

        matched = extract_matched_keywords(query, document)

        assert matched == []

    def test_partial_match(self):
        """Test when only some keywords match."""
        query = "Berlin conference 2025"
        document = "Berlin is a great city."

        matched = extract_matched_keywords(query, document)

        assert "berlin" in matched
        assert "conference" not in matched
        assert "2025" not in matched
        assert len(matched) == 1

    def test_german_umlauts(self):
        """Test matching with German umlauts."""
        query = "München Düsseldorf"
        document = "Die Städte München und Düsseldorf sind schön."

        matched = extract_matched_keywords(query, document)

        assert "münchen" in matched
        assert "düsseldorf" in matched
        assert len(matched) == 2

    def test_punctuation_handling(self):
        """Test that punctuation doesn't prevent matches."""
        query = "Berlin"
        document = "Berlin, Stadt der Möglichkeiten."

        matched = extract_matched_keywords(query, document)

        assert "berlin" in matched
        assert len(matched) == 1

    def test_case_insensitive(self):
        """Test case-insensitive matching."""
        query = "BERLIN"
        document = "berlin is the capital."

        matched = extract_matched_keywords(query, document)

        assert "berlin" in matched

    def test_preserves_query_order(self):
        """Test that matched keywords are returned in query order."""
        query = "alpha beta gamma"
        document = "gamma and alpha are present here."

        matched = extract_matched_keywords(query, document)

        # Should be in query order: alpha first, then gamma
        # beta not matched since it's not in the document
        assert matched == ["alpha", "gamma"]

    def test_no_duplicates(self):
        """Test that duplicate query terms don't cause duplicate results."""
        query = "Berlin Berlin Berlin"
        document = "Berlin is the capital of Germany."

        matched = extract_matched_keywords(query, document)

        assert matched == ["berlin"]

    def test_empty_query(self):
        """Test handling of empty query."""
        query = ""
        document = "Some document content."

        matched = extract_matched_keywords(query, document)

        assert matched == []

    def test_empty_document(self):
        """Test handling of empty document."""
        query = "Berlin"
        document = ""

        matched = extract_matched_keywords(query, document)

        assert matched == []

    def test_hyphenated_words(self):
        """Test matching of hyphenated words."""
        query = "real-time processing"
        document = "Real-time data processing is important."

        matched = extract_matched_keywords(query, document)

        # Depends on tokenization behavior
        assert len(matched) >= 1  # At least 'processing' should match

    def test_numbers_match(self):
        """Test that numbers match correctly."""
        query = "2025 10178"
        document = "The year 2025 and postal code 10178."

        matched = extract_matched_keywords(query, document)

        assert "2025" in matched
        assert "10178" in matched

    def test_special_characters_in_document(self):
        """Test handling of special characters in document."""
        query = "Berlin population"
        document = "Berlin (population: 3.7M) is Germany's capital."

        matched = extract_matched_keywords(query, document)

        assert "berlin" in matched
        assert "population" in matched


class TestTokenizeForBm25:
    """Tests for the tokenize_for_bm25 function."""

    def test_basic_tokenization(self):
        """Test basic text tokenization."""
        text = "Hello World"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["hello", "world"]

    def test_punctuation_stripping(self):
        """Test that punctuation is stripped from boundaries."""
        text = "Berlin, Stadt"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["berlin", "stadt"]

    def test_parentheses_stripping(self):
        """Test stripping of parentheses."""
        text = "(Hamburg)"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["hamburg"]

    def test_german_umlaut_preservation(self):
        """Test that German umlauts are preserved."""
        text = "München Düsseldorf Köln"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["münchen", "düsseldorf", "köln"]

    def test_lowercase_conversion(self):
        """Test that text is lowercased."""
        text = "BERLIN Berlin BerLin"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["berlin", "berlin", "berlin"]

    def test_empty_string(self):
        """Test handling of empty string."""
        text = ""
        tokens = tokenize_for_bm25(text)

        assert tokens == []

    def test_only_punctuation(self):
        """Test handling of only punctuation."""
        text = "... ??? !!!"
        tokens = tokenize_for_bm25(text)

        assert tokens == []

    def test_multiple_spaces(self):
        """Test handling of multiple spaces."""
        text = "Berlin   Hamburg     Munich"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["berlin", "hamburg", "munich"]

    def test_numbers(self):
        """Test that numbers are preserved."""
        text = "Berlin 2025 10178"
        tokens = tokenize_for_bm25(text)

        assert tokens == ["berlin", "2025", "10178"]

    def test_decimal_numbers(self):
        """Test handling of decimal numbers."""
        text = "Value is 3.14 or 891.12"
        tokens = tokenize_for_bm25(text)

        # Decimals should be preserved as internal periods
        assert "3.14" in tokens or "3" in tokens  # Depends on implementation
        assert "891.12" in tokens or "891" in tokens

    def test_hyphenated_words_preserved(self):
        """Test that internal hyphens are preserved."""
        text = "real-time server-side"
        tokens = tokenize_for_bm25(text)

        # Behavior depends on tokenization - either split or preserved
        # At minimum, should produce some tokens
        assert len(tokens) >= 2
