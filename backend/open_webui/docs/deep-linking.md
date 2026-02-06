# Deep Linking Specification (Future Enhancement)

This document outlines the planned approach for deep linking to specific pages within documents in Open WebUI citations.

## Overview

Deep linking allows users to click on a citation and jump directly to the relevant page in a document viewer. This enhances the RAG experience by making verification faster.

## Current State

As of December 2025:
- Page numbers are **displayed** in citation UI
- Page numbers are **stored** in chunk metadata
- **No clickable deep links** to specific pages yet

## Proposed URL Patterns

### Internal File Viewer

```
/api/v1/files/{file_id}/content#page={page_number}
```

Where:
- `file_id`: UUID of the uploaded file
- `page_number`: 1-based page number for URL (converted from 0-based internal index)

Example:
```
/api/v1/files/550e8400-e29b-41d4-a716-446655440000/content#page=5
```

### PDF.js External Viewer

For PDFs specifically, PDF.js supports page navigation:

```
/pdfjs/web/viewer.html?file=/api/v1/files/{file_id}/content#page={page_number}
```

Example:
```
/pdfjs/web/viewer.html?file=/api/v1/files/550e8400-e29b-41d4-a716-446655440000/content#page=5
```

## Metadata Requirements

For deep linking to work, chunks must include:

| Field | Required | Description |
|-------|----------|-------------|
| file_id | Yes | UUID of the original uploaded file |
| page | Yes | 0-based page index |
| page_label | Recommended | Human-readable page identifier |

### Current Metadata Flow

```
External Loader → chunk.metadata.page (0-based)
                  ↓
Open WebUI indexing → preserves metadata
                      ↓
Retrieval → chunk.metadata.file_id (added during indexing)
            ↓
Citation UI → displays (page + 1)
```

### Required Addition

For deep links, the `file_id` must be preserved through the retrieval pipeline:

```python
# In middleware.py source construction
metadata = {
    "file_id": file.id,  # Already present
    "page": doc.metadata.get("page"),  # Must preserve
    "page_label": doc.metadata.get("page_label"),
}
```

## Implementation Roadmap

### Phase 1: Metadata Preservation (Current)
- [x] External loaders provide 0-based `page` index
- [x] `page` metadata preserved through indexing
- [x] `page` displayed in citation modal
- [ ] `file_id` available in citation metadata

### Phase 2: Link Generation
- [ ] Construct deep link URLs in CitationModal.svelte
- [ ] Detect file type to choose appropriate viewer
- [ ] Handle files without page support gracefully

### Phase 3: Viewer Integration
- [ ] Integrate PDF.js viewer component
- [ ] Support `#page=N` hash navigation
- [ ] Handle PPTX slide navigation (if supported)

## CitationModal Implementation Sketch

```svelte
<script>
    function getDeepLink(document) {
        const fileId = document.metadata?.file_id;
        const page = document.metadata?.page;
        const docType = document.metadata?.document_type;

        if (!fileId || page === undefined) return null;

        const pageNum = page + 1; // Convert to 1-based for URL

        if (docType === 'pdf') {
            return `/pdfjs/web/viewer.html?file=/api/v1/files/${fileId}/content#page=${pageNum}`;
        }

        // Default: open file with page hash
        return `/api/v1/files/${fileId}/content#page=${pageNum}`;
    }
</script>

{#if getDeepLink(document)}
    <a href={getDeepLink(document)} target="_blank" class="text-blue-500 hover:underline">
        View page {document.metadata.page + 1}
    </a>
{:else}
    (page {document.metadata.page + 1})
{/if}
```

## Current Limitations

1. **No built-in page anchor support** - Open WebUI's file viewer doesn't parse `#page=N`
2. **PDF.js not bundled** - Would need to add PDF.js viewer component
3. **PPTX/XLSX viewers** - No standard web viewer with page navigation
4. **External file URLs** - Deep linking harder for non-uploaded external sources

## Alternatives Considered

### Option A: Open file and scroll to position
- Pro: Works with any text viewer
- Con: Can't scroll to exact page in PDF

### Option B: Embed PDF.js viewer
- Pro: Native PDF page navigation
- Con: Significant frontend addition, only works for PDFs

### Option C: Generate screenshots per page
- Pro: Universal format
- Con: High storage cost, loses text selection

**Recommendation:** Start with Option B (PDF.js) for PDFs, add others incrementally.

## Security Considerations

- Deep links should respect file access permissions
- `file_id` in URLs must validate user access
- External viewers must not leak file content URLs

## Related Documentation

- [External Loader API](./external-loader-api.md) - Metadata schema specification
- [CitationModal.svelte](../../../src/lib/components/chat/Messages/Citations/CitationModal.svelte) - Citation display component

## Version History

| Version | Date | Status |
|---------|------|--------|
| 0.1 | 2025-12-10 | Initial specification (not implemented) |
