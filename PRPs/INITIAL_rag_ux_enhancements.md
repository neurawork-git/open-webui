# RAG UX Enhancements - Initial Requirements

## Project Overview

This document specifies three interconnected RAG user experience improvements for Open WebUI:
1. **Enhanced External Document Loader** - Page-aware chunking with metadata for deep linking
2. **Reranking Toggle** - Ability to disable reranking and show raw hybrid scores
3. **BM25 Keyword Highlighting** - Visual marking of matched keywords in source snippets

**Branch:** `feature/rag-improvements`
**Related Project:** Open WebUI RAG Improvements (Archon ID: `0029a544-b4ce-4c19-b60d-8db912690342`)

---

## Feature 1: Enhanced External Document Loader

### Problem Statement

The current external document loader (`backend/open_webui/retrieval/loaders/external_document.py`) accepts page-aware metadata from external services, but:

1. **Page numbers are not displayed** in the citation UI (CitationModal.svelte)
2. **Deep linking** to specific pages is not supported for external loader documents
3. **Pre-chunked documents** cannot signal to Open WebUI that chunks should be preserved as-is
4. **No standard API contract** documents the expected metadata fields for page-aware processing

The existing markitdown_service at `C:\Users\neura\Documents\Repositories\markitdown_service` already returns page-aware documents:

```python
# Current markitdown_service output format
{
    "page_content": "...",
    "metadata": {
        "source": "filename.pdf",
        "page": 1  # 1-indexed page number
    }
}
```

### Current Open WebUI External Loader Interface

**Endpoint:** `PUT {EXTERNAL_DOCUMENT_LOADER_URL}/process`

**Headers:**
- `Content-Type`: MIME type of file
- `Authorization`: Bearer token (API key)
- `X-Filename`: URL-encoded filename

**Request Body:** Raw binary file data

**Response Format (Current):**
```json
// Single document
{
    "page_content": "text content",
    "metadata": {"source": "file.pdf"}
}

// Multiple documents
[
    {"page_content": "page 1", "metadata": {"source": "file.pdf"}},
    {"page_content": "page 2", "metadata": {"source": "file.pdf"}}
]
```

### Research: How Internal Loaders Handle Pages

The Mistral OCR loader (`backend/open_webui/retrieval/loaders/mistral.py:556-568`) demonstrates the correct metadata pattern:

```python
metadata = {
    "page": page_index,           # 0-based index
    "page_label": page_index + 1, # 1-based for UI display
    "total_pages": total_pages,
    "file_name": self.file_name,
    "file_size": self.file_size,
    "processing_engine": "mistral-ocr",
    "content_length": len(cleaned_content),
}
```

The citation modal (`src/lib/components/chat/Messages/Citations/CitationModal.svelte:155-160`) already checks for page metadata:
```svelte
{#if document.metadata?.page != null}
    <span class="text-xs text-gray-500">(page {document.metadata.page + 1})</span>
{/if}
```

**Key Finding:** Open WebUI expects 0-based `page` index and displays `page + 1` in the UI.

### Requirements

#### R1.1: Standardized Metadata Schema for External Loaders

External loaders MUST return documents with the following metadata structure:

```json
{
    "page_content": "chunk text content",
    "metadata": {
        // Required fields
        "source": "filename.pdf",

        // Page tracking (recommended for paged documents)
        "page": 0,              // 0-based index (for consistency with LangChain/Mistral)
        "page_label": "1",      // Human-readable label (can be "i", "ii", "Cover", etc.)
        "total_pages": 50,

        // Chunk positioning within page (optional, for sub-chunking support)
        "chunk_index": 0,           // Position of this chunk within the page
        "page_offset_start": 0,     // Character offset start within page
        "page_offset_end": 1234,    // Character offset end within page

        // Processing metadata (optional)
        "processing_engine": "markitdown",
        "document_type": "pdf",     // pdf, pptx, xlsx, docx, etc.
        "content_length": 1234
    }
}
```

#### R1.2: Update markitdown_service to Use 0-Based Page Index

Modify `C:\Users\neura\Documents\Repositories\markitdown_service\src\server.py` to output 0-based page index:

**Current (1-indexed):**
```python
"metadata": {
    "source": source_name,
    "page": page_num + 1  # 1-indexed
}
```

**Required (0-indexed with label):**
```python
"metadata": {
    "source": source_name,
    "page": page_num,           # 0-indexed
    "page_label": str(page_num + 1),  # Human-readable
    "total_pages": len(reader.pages),
    "processing_engine": "markitdown",
    "document_type": "pdf"
}
```

#### R1.3: Sub-Chunking Support

When Open WebUI's text splitter processes external loader documents:
- Preserve original `page` metadata on all sub-chunks
- Add `start_index` offset within the original chunk (already happens)
- The combination of `page` + `start_index` enables position reconstruction

**Current behavior (keep):** Text splitters already preserve metadata through chunking.

**No changes needed** - sub-chunking is already supported by design.

#### R1.4: Deep Link Support (Research Documentation)

For future implementation, deep linking to external viewers requires:

1. **File Storage URL Pattern:**
   ```
   /api/v1/files/{file_id}/content#page={page_number}
   ```

2. **PDF.js Integration (External Viewer):**
   ```
   /pdfjs/web/viewer.html?file=/api/v1/files/{file_id}/content#page={page_number}
   ```

3. **Metadata Requirements:**
   - `file_id` must be preserved in chunk metadata
   - `page` (0-based) must be present
   - URL construction happens in `CitationModal.svelte:67-82`

**Current limitation:** Open WebUI's file viewer doesn't support page anchors yet. This is documented for future enhancement.

### Implementation Tasks

| Task | File | Effort |
|------|------|--------|
| Update markitdown_service metadata schema | `markitdown_service/src/server.py` | 30 min |
| Document external loader API contract | New file: `docs/external-loader-api.md` | 1 hour |
| Verify page number displays in CitationModal | `CitationModal.svelte` | 15 min (test only) |
| Add total_pages to existing loaders (optional) | `external_document.py` | 30 min |

---

## Feature 2: Reranking Toggle

### Problem Statement

The reranking system sometimes produces questionable scores that obscure the raw hybrid search quality. Users need the ability to:
1. Disable reranking entirely and see raw hybrid (BM25 + vector) scores
2. Compare reranked vs. raw scores for debugging
3. Control this at both global and per-knowledge-base levels

### Current Architecture

**Reranking Pipeline (`backend/open_webui/retrieval/utils.py:302-441`):**

```
Query → EnsembleRetriever (BM25 + Vector) → RerankCompressor → Final Results
              ↓                                    ↓
      weights: [bm25_weight, 1-bm25_weight]    reranking_function
```

**Current disable mechanism:** Leave `RAG_RERANKING_MODEL` empty

**Problem:** When reranking is disabled, the system falls back to cosine similarity recalculation rather than using the original ensemble scores.

```python
# Current fallback (utils.py:1555-1572)
if reranking:
    scores = self.reranking_function(query, documents)
else:
    # Falls back to cosine similarity - NOT the raw hybrid scores!
    scores = util.cos_sim(query_embedding, document_embedding)[0]
```

### Requirements

#### R2.1: Explicit Reranking Disable Flag

Add a new setting `ENABLE_RAG_RERANKING` (default: `true`) that:
- When `false`, skips the RerankCompressor entirely
- Returns raw ensemble retriever scores directly
- Works independently of `RAG_RERANKING_MODEL` setting

#### R2.2: Per-Knowledge-Base Override

Extend `RagSettings` model to include reranking toggle:

```python
# backend/open_webui/models/knowledge.py
class RagSettings(BaseModel):
    top_k: Optional[int] = None
    top_k_reranker: Optional[int] = None
    relevance_threshold: Optional[float] = None
    enable_hybrid_search: Optional[bool] = None
    hybrid_bm25_weight: Optional[float] = None
    full_context: Optional[bool] = None
    enable_reranking: Optional[bool] = None  # NEW: Per-KB reranking toggle
```

#### R2.3: Score Pass-Through Mode

When reranking is disabled, the system should:
1. Return documents from EnsembleRetriever with their original ensemble scores
2. NOT recalculate scores via cosine similarity
3. Apply relevance threshold filtering on raw ensemble scores

**Implementation approach:**

```python
# In RerankCompressor.acompress_documents()
if not self.enable_reranking:
    # Pass through with original scores from ensemble retriever
    # Scores are already in documents from EnsembleRetriever
    return documents  # With original scores preserved
```

#### R2.4: Admin UI Toggle

Add toggle in Documents admin settings:
- Global: "Enable Reranking" checkbox (default: checked)
- Per-KB: Override option in knowledge base settings

### Configuration Cascade

```
Global ENABLE_RAG_RERANKING (default: true)
    ↓ overridden by
Knowledge Base enable_reranking (optional)
```

### Implementation Tasks

| Task | File | Effort |
|------|------|--------|
| Add `ENABLE_RAG_RERANKING` config | `config.py`, `env.py` | 30 min |
| Add to RagSettings model | `models/knowledge.py` | 15 min |
| Modify RerankCompressor to skip reranking | `retrieval/utils.py` | 1 hour |
| Pass raw scores through pipeline | `retrieval/utils.py` | 1 hour |
| Add UI toggle in admin settings | `Settings/Documents.svelte` | 30 min |
| Add per-KB setting in knowledge editor | KB settings component | 30 min |

---

## Feature 3: BM25 Keyword Highlighting

### Problem Statement

When hybrid search is enabled, users cannot see which keywords from their query matched via BM25. This makes it difficult to:
1. Understand why a document was retrieved
2. Quickly scan for relevant terms in long snippets
3. Debug hybrid search behavior

### Current Architecture

**BM25 Tokenization (`backend/open_webui/retrieval/utils.py:83-114`):**

```python
def tokenize_for_bm25(text: str) -> list[str]:
    """
    Tokenize text for BM25 scoring with proper punctuation handling.
    - Converts to lowercase
    - Removes punctuation from word boundaries
    - Preserves German umlauts and internal hyphens
    """
```

**Citation Display (`src/lib/components/chat/Messages/Citations/CitationModal.svelte:171-173`):**

```svelte
<pre class="whitespace-pre-wrap">{document.page_content || document}</pre>
```

**Key Insight:** The frontend receives documents but NOT the query or matched keywords.

### Requirements

#### R3.1: Backend - Compute Matched Keywords

When hybrid search is enabled, compute which BM25 tokens matched:

```python
# In get_sources_from_items() or query_doc_with_hybrid_search()
matched_keywords = []
query_tokens = tokenize_for_bm25(query)
for token in query_tokens:
    if token in document_tokens:  # Check if query token appears in doc
        matched_keywords.append(token)

# Add to metadata
metadata["bm25_matched_keywords"] = matched_keywords
```

#### R3.2: Enhanced Source Structure

Extend the source data passed to frontend:

```json
{
    "source": {"name": "...", "id": "..."},
    "document": ["chunk text..."],
    "metadata": [{
        "source": "...",
        "page": 0,
        "bm25_matched_keywords": ["berlin", "2025", "workshop"]
    }],
    "distances": [0.85],
    "query": "Berlin 2025 workshop"  // Optional: pass query for client-side highlighting
}
```

#### R3.3: Frontend - Color-Coded Highlighting

In CitationModal.svelte, implement keyword highlighting:

```svelte
<script>
    function highlightKeywords(text, keywords) {
        if (!keywords || keywords.length === 0) return text;

        // Color palette for different keywords
        const colors = [
            'bg-yellow-200 dark:bg-yellow-800',
            'bg-green-200 dark:bg-green-800',
            'bg-blue-200 dark:bg-blue-800',
            'bg-pink-200 dark:bg-pink-800'
        ];

        let result = text;
        keywords.forEach((keyword, idx) => {
            const color = colors[idx % colors.length];
            const regex = new RegExp(`\\b(${escapeRegex(keyword)})\\b`, 'gi');
            result = result.replace(regex, `<mark class="${color} font-semibold rounded px-0.5">$1</mark>`);
        });
        return result;
    }
</script>

{#if document.metadata?.bm25_matched_keywords?.length > 0}
    <div class="whitespace-pre-wrap">
        {@html highlightKeywords(document.page_content, document.metadata.bm25_matched_keywords)}
    </div>
{:else}
    <pre class="whitespace-pre-wrap">{document.page_content}</pre>
{/if}
```

#### R3.4: Keyword Legend

Display a legend showing which colors map to which query terms:

```svelte
{#if document.metadata?.bm25_matched_keywords?.length > 0}
    <div class="flex flex-wrap gap-2 mb-2 text-xs">
        <span class="text-gray-500">Matched:</span>
        {#each document.metadata.bm25_matched_keywords as keyword, idx}
            <span class="px-1.5 py-0.5 rounded {colors[idx % colors.length]}">
                {keyword}
            </span>
        {/each}
    </div>
{/if}
```

#### R3.5: Only When Hybrid Search Enabled

Keyword highlighting should only appear when:
- `enable_hybrid_search` is true
- `bm25_matched_keywords` array is non-empty

When hybrid search is disabled, show plain text as before.

### Implementation Tasks

| Task | File | Effort |
|------|------|--------|
| Compute matched keywords in backend | `retrieval/utils.py` | 1 hour |
| Add to source metadata structure | `utils/middleware.py` | 30 min |
| Create highlightKeywords function | `CitationModal.svelte` | 1 hour |
| Add keyword legend component | `CitationModal.svelte` | 30 min |
| Add dark mode support for colors | `CitationModal.svelte` | 15 min |
| Test with German text (umlauts) | Manual testing | 30 min |

---

## Technical Dependencies

### Affected Files

**Backend:**
- `backend/open_webui/retrieval/utils.py` - BM25 keyword extraction, reranking toggle
- `backend/open_webui/retrieval/loaders/external_document.py` - Metadata validation
- `backend/open_webui/utils/middleware.py` - Source structure enrichment
- `backend/open_webui/config.py` - New config: `ENABLE_RAG_RERANKING`
- `backend/open_webui/models/knowledge.py` - RagSettings extension
- `backend/open_webui/routers/retrieval.py` - Config endpoints

**Frontend:**
- `src/lib/components/chat/Messages/Citations/CitationModal.svelte` - Highlighting, page display
- `src/lib/components/admin/Settings/Documents.svelte` - Reranking toggle
- `src/lib/apis/streaming/index.ts` - Source structure parsing

**External:**
- `markitdown_service/src/server.py` - 0-based page metadata

### Shared Code Patterns

All features follow existing patterns:
- Per-KB settings use cascading override model (`RagSettings`)
- Config uses `PersistentConfig` for database storage
- UI toggles follow existing Documents.svelte patterns

---

## Testing Strategy

### Unit Tests

1. **BM25 Keyword Matching:**
   - Test `tokenize_for_bm25()` with various inputs
   - Test keyword extraction returns correct matches
   - Test German umlauts preserved

2. **Reranking Toggle:**
   - Test scores differ between reranked and raw modes
   - Test per-KB override works correctly

3. **External Loader Metadata:**
   - Test 0-indexed pages work correctly
   - Test metadata survives chunking pipeline

### Integration Tests

1. Upload PDF via markitdown_service → verify page numbers in citations
2. Enable/disable reranking → verify score differences
3. Hybrid search query → verify keyword highlighting appears

### Manual Testing

1. Upload multi-page PDF, check citation shows correct page
2. Compare same query with reranking on/off
3. German query → verify umlauts highlighted correctly

---

## Success Criteria

1. **External Loader:** Page numbers display correctly in citation modal for documents from markitdown_service
2. **Reranking Toggle:** Users can disable reranking and see raw hybrid scores; setting cascades properly
3. **Keyword Highlighting:** BM25 matched terms are visibly highlighted with distinct colors; legend shows query terms

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing external loaders | Medium | Backward compatible - new fields optional |
| Reranking toggle affects quality | Low | Default to enabled (current behavior) |
| XSS via keyword highlighting | High | Use Svelte's HTML sanitization, escape regex |
| Performance impact of keyword extraction | Low | O(n) where n = query tokens (typically <10) |

---

## Estimated Effort

| Feature | Backend | Frontend | Testing | Total |
|---------|---------|----------|---------|-------|
| External Loader Metadata | 2h | 0.5h | 1h | 3.5h |
| Reranking Toggle | 3h | 1h | 1h | 5h |
| BM25 Highlighting | 2h | 2.5h | 1h | 5.5h |
| **Total** | **7h** | **4h** | **3h** | **14h** |

---

## Related Documentation

- `RAG_EXECUTIVE_SUMMARY.md` - Overall RAG improvement roadmap
- `PRPs/BM25_TOKENIZATION_FIX.md` - BM25 tokenization implementation
- `PRPs/PRP_rag_per_level_settings.md` - Per-KB settings architecture
- Mistral OCR loader as reference: `backend/open_webui/retrieval/loaders/mistral.py:516-592`
