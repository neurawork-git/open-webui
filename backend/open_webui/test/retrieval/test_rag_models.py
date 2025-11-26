"""
Unit tests for RAG-related Pydantic models.

Tests RagSettings, KnowledgeMeta, and their behavior in forms.
"""

import pytest
from pydantic import ValidationError
from open_webui.models.knowledge import RagSettings, KnowledgeMeta, KnowledgeForm


class TestRagSettings:
    """Tests for RagSettings Pydantic model."""

    # ==========================================
    # Basic Instantiation Tests
    # ==========================================

    def test_empty_rag_settings(self):
        """Test that RagSettings can be created with no arguments."""
        settings = RagSettings()
        assert settings.top_k is None
        assert settings.top_k_reranker is None
        assert settings.relevance_threshold is None
        assert settings.enable_hybrid_search is None
        assert settings.hybrid_bm25_weight is None
        assert settings.full_context is None

    def test_full_rag_settings(self):
        """Test that all RAG settings can be set."""
        settings = RagSettings(
            top_k=10,
            top_k_reranker=5,
            relevance_threshold=0.7,
            enable_hybrid_search=True,
            hybrid_bm25_weight=0.4,
            full_context=False,
        )
        assert settings.top_k == 10
        assert settings.top_k_reranker == 5
        assert settings.relevance_threshold == 0.7
        assert settings.enable_hybrid_search is True
        assert settings.hybrid_bm25_weight == 0.4
        assert settings.full_context is False

    def test_partial_rag_settings(self):
        """Test that RagSettings can be created with partial values."""
        settings = RagSettings(top_k=5, relevance_threshold=0.8)
        assert settings.top_k == 5
        assert settings.relevance_threshold == 0.8
        assert settings.top_k_reranker is None
        assert settings.enable_hybrid_search is None

    # ==========================================
    # Type Handling Tests
    # ==========================================

    def test_integer_fields(self):
        """Test integer field types."""
        settings = RagSettings(top_k=5, top_k_reranker=3)
        assert isinstance(settings.top_k, int)
        assert isinstance(settings.top_k_reranker, int)

    def test_float_fields(self):
        """Test float field types."""
        settings = RagSettings(relevance_threshold=0.5, hybrid_bm25_weight=0.3)
        assert isinstance(settings.relevance_threshold, float)
        assert isinstance(settings.hybrid_bm25_weight, float)

    def test_boolean_fields(self):
        """Test boolean field types."""
        settings = RagSettings(enable_hybrid_search=True, full_context=False)
        assert isinstance(settings.enable_hybrid_search, bool)
        assert isinstance(settings.full_context, bool)

    def test_zero_values_preserved(self):
        """Test that zero values are preserved (not treated as None)."""
        settings = RagSettings(
            top_k=0,
            relevance_threshold=0.0,
            hybrid_bm25_weight=0,
        )
        assert settings.top_k == 0
        assert settings.relevance_threshold == 0.0
        assert settings.hybrid_bm25_weight == 0

    def test_false_boolean_preserved(self):
        """Test that False booleans are preserved."""
        settings = RagSettings(enable_hybrid_search=False, full_context=False)
        assert settings.enable_hybrid_search is False
        assert settings.full_context is False

    # ==========================================
    # Extra Fields Handling Tests (extra="ignore")
    # ==========================================

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored due to ConfigDict(extra='ignore')."""
        settings = RagSettings(
            top_k=5,
            unknown_field="should_be_ignored",
            another_unknown=123,
        )
        assert settings.top_k == 5
        assert not hasattr(settings, "unknown_field")
        assert not hasattr(settings, "another_unknown")

    # ==========================================
    # Serialization Tests
    # ==========================================

    def test_model_dump(self):
        """Test that model_dump works correctly."""
        settings = RagSettings(top_k=5, relevance_threshold=0.7)
        data = settings.model_dump()
        assert data["top_k"] == 5
        assert data["relevance_threshold"] == 0.7
        assert data["enable_hybrid_search"] is None

    def test_model_dump_exclude_none(self):
        """Test model_dump with exclude_none."""
        settings = RagSettings(top_k=5)
        data = settings.model_dump(exclude_none=True)
        assert data == {"top_k": 5}

    def test_from_dict(self):
        """Test creating RagSettings from a dict."""
        data = {"top_k": 10, "relevance_threshold": 0.8}
        settings = RagSettings(**data)
        assert settings.top_k == 10
        assert settings.relevance_threshold == 0.8


class TestKnowledgeMeta:
    """Tests for KnowledgeMeta Pydantic model."""

    # ==========================================
    # Basic Instantiation Tests
    # ==========================================

    def test_empty_knowledge_meta(self):
        """Test that KnowledgeMeta can be created with no arguments."""
        meta = KnowledgeMeta()
        assert meta.rag_settings is None

    def test_knowledge_meta_with_rag_settings(self):
        """Test KnowledgeMeta with RagSettings."""
        rag = RagSettings(top_k=5, relevance_threshold=0.7)
        meta = KnowledgeMeta(rag_settings=rag)
        assert meta.rag_settings is not None
        assert meta.rag_settings.top_k == 5
        assert meta.rag_settings.relevance_threshold == 0.7

    def test_knowledge_meta_from_dict(self):
        """Test creating KnowledgeMeta from nested dict."""
        data = {"rag_settings": {"top_k": 8, "enable_hybrid_search": True}}
        meta = KnowledgeMeta(**data)
        assert meta.rag_settings is not None
        assert meta.rag_settings.top_k == 8
        assert meta.rag_settings.enable_hybrid_search is True

    # ==========================================
    # Extra Fields Handling Tests (extra="allow")
    # ==========================================

    def test_extra_fields_allowed(self):
        """Test that extra fields are allowed due to ConfigDict(extra='allow')."""
        meta = KnowledgeMeta(
            rag_settings=RagSettings(top_k=5),
            custom_field="custom_value",
            another_custom=123,
        )
        assert meta.rag_settings.top_k == 5
        assert meta.custom_field == "custom_value"
        assert meta.another_custom == 123

    def test_future_extensibility(self):
        """Test that KnowledgeMeta allows for future fields without schema changes."""
        # This simulates adding new features without breaking existing code
        meta = KnowledgeMeta(
            rag_settings=RagSettings(top_k=5),
            future_feature_x={"enabled": True, "value": 42},
        )
        assert meta.rag_settings.top_k == 5
        assert meta.future_feature_x == {"enabled": True, "value": 42}

    # ==========================================
    # Serialization Tests
    # ==========================================

    def test_model_dump_nested(self):
        """Test that nested model_dump works correctly."""
        meta = KnowledgeMeta(rag_settings=RagSettings(top_k=5, full_context=True))
        data = meta.model_dump()
        assert data["rag_settings"]["top_k"] == 5
        assert data["rag_settings"]["full_context"] is True

    def test_model_dump_with_extra_fields(self):
        """Test model_dump includes extra fields."""
        meta = KnowledgeMeta(rag_settings=None, custom="value")
        data = meta.model_dump()
        assert "custom" in data
        assert data["custom"] == "value"


class TestKnowledgeFormWithMeta:
    """Tests for KnowledgeForm with meta field containing RAG settings.

    Note: KnowledgeForm.meta is typed as Optional[dict] for API flexibility.
    The KnowledgeMeta model is used for type hints and validation elsewhere,
    but the form accepts raw dicts directly from API requests.
    """

    def test_knowledge_form_without_meta(self):
        """Test KnowledgeForm can be created without meta."""
        form = KnowledgeForm(
            name="Test KB",
            description="Test description",
        )
        assert form.name == "Test KB"
        assert form.description == "Test description"
        assert form.meta is None

    def test_knowledge_form_with_meta_dict(self):
        """Test KnowledgeForm with meta as dict containing RAG settings."""
        # meta field is Optional[dict], not Optional[KnowledgeMeta]
        form = KnowledgeForm(
            name="Test KB",
            description="Test description",
            meta={"rag_settings": {"top_k": 10}},
        )
        assert form.name == "Test KB"
        assert form.meta is not None
        assert form.meta["rag_settings"]["top_k"] == 10

    def test_knowledge_form_from_api_payload(self):
        """Test KnowledgeForm from typical API request payload."""
        # Simulates what would come from a frontend request
        payload = {
            "name": "My Knowledge Base",
            "description": "Contains important documents",
            "meta": {
                "rag_settings": {
                    "top_k": 8,
                    "relevance_threshold": 0.6,
                    "enable_hybrid_search": True,
                }
            },
        }
        form = KnowledgeForm(**payload)
        assert form.name == "My Knowledge Base"
        # Access as dict since meta is Optional[dict]
        assert form.meta["rag_settings"]["top_k"] == 8
        assert form.meta["rag_settings"]["relevance_threshold"] == 0.6
        assert form.meta["rag_settings"]["enable_hybrid_search"] is True

    def test_knowledge_form_model_dump_for_api(self):
        """Test that model_dump produces valid API response format."""
        form = KnowledgeForm(
            name="Test KB",
            description="Test description",
            meta={"rag_settings": {"top_k": 5, "full_context": False}},
        )
        data = form.model_dump()
        assert data["name"] == "Test KB"
        assert data["meta"]["rag_settings"]["top_k"] == 5
        assert data["meta"]["rag_settings"]["full_context"] is False

    def test_knowledge_meta_validation_separate(self):
        """Test that KnowledgeMeta can validate dict data when needed."""
        # This demonstrates how to validate meta dict with KnowledgeMeta
        raw_meta = {"rag_settings": {"top_k": 10, "full_context": True}}
        validated = KnowledgeMeta(**raw_meta)
        assert validated.rag_settings.top_k == 10
        assert validated.rag_settings.full_context is True


class TestRagSettingsEdgeCases:
    """Edge case tests for RAG settings."""

    def test_negative_top_k_allowed(self):
        """Test that negative top_k is allowed (validation is elsewhere)."""
        # Note: Schema allows any int - range validation may be at API level
        settings = RagSettings(top_k=-1)
        assert settings.top_k == -1

    def test_threshold_out_of_range_allowed(self):
        """Test that out-of-range threshold is allowed (validation elsewhere)."""
        # Note: Schema allows any float - range validation may be at API level
        settings = RagSettings(relevance_threshold=1.5)
        assert settings.relevance_threshold == 1.5

    def test_string_to_int_coercion(self):
        """Test that string numbers are coerced to int."""
        settings = RagSettings(top_k="5")  # type: ignore
        assert settings.top_k == 5
        assert isinstance(settings.top_k, int)

    def test_string_to_float_coercion(self):
        """Test that string numbers are coerced to float."""
        settings = RagSettings(relevance_threshold="0.7")  # type: ignore
        assert settings.relevance_threshold == 0.7
        assert isinstance(settings.relevance_threshold, float)

    def test_deeply_nested_rag_settings_access(self):
        """Test accessing RAG settings through multiple levels."""
        # Simulates the access pattern in middleware
        # KnowledgeForm.meta is Optional[dict], so we use dict directly
        form = KnowledgeForm(
            name="Test",
            description="Test",
            meta={
                "rag_settings": {
                    "top_k": 5,
                    "relevance_threshold": 0.7,
                }
            },
        )

        # Simulate middleware access pattern (exactly as done in middleware.py)
        meta_dict = form.meta if isinstance(form.meta, dict) else {}
        rag_dict = meta_dict.get("rag_settings", {})

        assert rag_dict.get("top_k") == 5
        assert rag_dict.get("relevance_threshold") == 0.7
        assert rag_dict.get("enable_hybrid_search") is None
