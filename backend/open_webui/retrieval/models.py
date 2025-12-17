"""
RAG Query Settings Models

This module provides a unified Pydantic model for RAG query configuration,
eliminating the need to pass individual parameters through function signatures.
"""

from typing import Optional
from pydantic import BaseModel, Field


class RAGQuerySettings(BaseModel):
    """
    Unified settings object for RAG queries.

    This model encapsulates all retrieval-related configuration and supports
    cascading overrides from global settings to per-knowledge-base settings.

    Priority (highest to lowest):
    1. Per-query overrides (from API request)
    2. Per-knowledge-base settings
    3. User settings
    4. Global defaults (from app.state.config)
    """

    # Core retrieval parameters
    top_k: int = Field(default=3, ge=1, description="Number of top results to retrieve from vector search")
    top_k_reranker: int = Field(default=3, ge=1, description="Number of results after reranking")
    relevance_threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum relevance score (0.0-1.0)")

    # Hybrid search parameters
    enable_hybrid_search: bool = Field(default=False, description="Enable BM25 + vector hybrid search")
    hybrid_bm25_weight: float = Field(default=0.5, ge=0.0, le=1.0, description="BM25 weight in hybrid search (0.0-1.0)")
    enable_enriched_texts: bool = Field(default=False, description="Include filename, title, source in BM25 search")

    # Reranking parameters
    enable_reranking: bool = Field(default=True, description="Enable reranking of results")

    # Context parameters
    full_context: bool = Field(default=False, description="Return full document context instead of chunks")

    class Config:
        extra = "ignore"  # Ignore unknown fields for forward compatibility

    @classmethod
    def from_config(cls, config) -> "RAGQuerySettings":
        """
        Create RAGQuerySettings from app.state.config object.

        Args:
            config: The app.state.config object containing global RAG settings

        Returns:
            RAGQuerySettings with values from global config
        """
        return cls(
            top_k=getattr(config, 'TOP_K', 3),
            top_k_reranker=getattr(config, 'TOP_K_RERANKER', 3),
            relevance_threshold=getattr(config, 'RELEVANCE_THRESHOLD', 0.0),
            enable_hybrid_search=getattr(config, 'ENABLE_RAG_HYBRID_SEARCH', False),
            hybrid_bm25_weight=getattr(config, 'HYBRID_BM25_WEIGHT', 0.5),
            enable_enriched_texts=getattr(config, 'ENABLE_RAG_HYBRID_SEARCH_ENRICHED_TEXTS', False),
            enable_reranking=getattr(config, 'ENABLE_RAG_RERANKING', True),
            full_context=getattr(config, 'RAG_FULL_CONTEXT', False),
        )

    def merge_with(self, overrides: Optional[dict]) -> "RAGQuerySettings":
        """
        Create a new RAGQuerySettings with overrides applied.

        This enables the cascading override pattern:
        global_settings.merge_with(user_settings).merge_with(kb_settings).merge_with(query_settings)

        Args:
            overrides: Dictionary of settings to override. Keys should match field names.
                      None values are ignored (original value preserved).

        Returns:
            New RAGQuerySettings instance with overrides applied
        """
        if not overrides:
            return self

        # Map from various naming conventions to our canonical field names
        field_mappings = {
            # Direct matches
            'top_k': 'top_k',
            'top_k_reranker': 'top_k_reranker',
            'relevance_threshold': 'relevance_threshold',
            'enable_hybrid_search': 'enable_hybrid_search',
            'hybrid_bm25_weight': 'hybrid_bm25_weight',
            'enable_enriched_texts': 'enable_enriched_texts',
            'enable_reranking': 'enable_reranking',
            'full_context': 'full_context',
            # Alternative names used in forms/API
            'k': 'top_k',
            'k_reranker': 'top_k_reranker',
            'r': 'relevance_threshold',
            'hybrid': 'enable_hybrid_search',
        }

        # Start with current values
        current = self.model_dump()

        # Apply overrides
        for key, value in overrides.items():
            if value is None:
                continue
            canonical_key = field_mappings.get(key, key)
            if canonical_key in current:
                current[canonical_key] = value

        return RAGQuerySettings(**current)

    def to_query_params(self) -> dict:
        """
        Convert to the parameter dict format used by query functions.

        Returns:
            Dictionary with keys matching query function parameters
        """
        return {
            'k': self.top_k,
            'k_reranker': self.top_k_reranker,
            'r': self.relevance_threshold,
            'hybrid_bm25_weight': self.hybrid_bm25_weight,
            'enable_enriched_texts': self.enable_enriched_texts,
            'enable_reranking': self.enable_reranking,
        }


def merge_rag_settings(*settings_dicts: Optional[dict]) -> dict:
    """
    Legacy helper function for merging RAG settings dictionaries.

    Maintained for backward compatibility. New code should use
    RAGQuerySettings.merge_with() instead.

    Args:
        *settings_dicts: Variable number of settings dictionaries.
                        Later dictionaries override earlier ones.
                        None values within dicts are ignored.

    Returns:
        Merged settings dictionary
    """
    result = {}

    for settings in settings_dicts:
        if settings is None:
            continue
        for key, value in settings.items():
            if value is not None:
                result[key] = value

    return result
