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
    async def from_config(cls) -> "RAGQuerySettings":
        """
        Create RAGQuerySettings from the global per-key DB config (open_webui.models.config.Config).

        Reads the same 'rag.*' keys that routers/retrieval.py's RETRIEVAL_CONFIG_KEYS
        maps the admin-facing UPPER_CASE settings to.

        Returns:
            RAGQuerySettings with values from global config
        """
        from open_webui.models.config import Config

        values = await Config.get_many(
            'rag.top_k',
            'rag.top_k_reranker',
            'rag.relevance_threshold',
            'rag.enable_hybrid_search',
            'rag.hybrid_bm25_weight',
            'rag.enable_hybrid_search_enriched_texts',
            'rag.enable_reranking',
            'rag.full_context',
        )
        return cls(
            top_k=values.get('rag.top_k', 3),
            top_k_reranker=values.get('rag.top_k_reranker', 3),
            relevance_threshold=values.get('rag.relevance_threshold', 0.0),
            enable_hybrid_search=values.get('rag.enable_hybrid_search', False),
            hybrid_bm25_weight=values.get('rag.hybrid_bm25_weight', 0.5),
            enable_enriched_texts=values.get('rag.enable_hybrid_search_enriched_texts', False),
            enable_reranking=values.get('rag.enable_reranking', True),
            full_context=values.get('rag.full_context', False),
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
