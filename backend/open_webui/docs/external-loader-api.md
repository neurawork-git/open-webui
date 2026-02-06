# External Document Loader API Specification

This document specifies the API contract for external document loaders in Open WebUI.

## Overview

External document loaders enable processing documents via external services (e.g., specialized OCR, PDF extraction, or format conversion services). Open WebUI communicates with these services via HTTP and expects a standardized response format.

## API Endpoint

### PUT /process

Accepts raw file bytes and returns structured document chunks.

**Request:**
- Method: `PUT`
- Body: Raw file bytes
- Headers:
  - `Content-Type`: MIME type of the file (e.g., `application/pdf`)
  - `X-Filename`: Original filename (optional but recommended)

**Response:**
- Content-Type: `application/json`
- Body: Array of document objects

```json
[
  {
    "page_content": "Document text content for this chunk...",
    "metadata": {
      "source": "document.pdf",
      "page": 0,
      "page_label": "1",
      "total_pages": 10,
      "document_type": "pdf",
      "processing_engine": "my-loader"
    }
  }
]
```

## Metadata Schema

### Required Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| source | string | Yes | Filename or source identifier |
| page | integer | Recommended | 0-based page index |

### Recommended Fields

| Field | Type | Description |
|-------|------|-------------|
| page_label | string | Human-readable page label (e.g., "1", "i", "A-1") |
| total_pages | integer | Total number of pages in document |
| document_type | string | File type: pdf, pptx, xlsx, docx, etc. |
| processing_engine | string | Identifier for the loader service |
| content_length | integer | Character count of page_content |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| start_index | integer | Character offset within page (added by sub-chunking) |
| chunk_index | integer | Chunk number within page |
| total_chunks | integer | Total chunks from this page |

## Page Indexing Convention

**CRITICAL: Open WebUI uses 0-based page indexing.**

The `page` field must be 0-indexed. Open WebUI displays page numbers as `page + 1` in the UI.

| page value | UI displays |
|------------|-------------|
| 0 | "page 1" |
| 1 | "page 2" |
| 9 | "page 10" |

### Reference Implementation

From Open WebUI's CitationModal.svelte:
```svelte
{#if document.metadata?.page !== undefined}
  (page {document.metadata.page + 1})
{/if}
```

### Comparison with Internal Loaders

Open WebUI's Mistral OCR loader uses this pattern:
```python
metadata = {
    "page": page_index,      # 0-based (for internal use)
    "page_label": str(page_index + 1),  # Human-readable
}
```

## Document Type Examples

### PDF Documents

```json
{
  "page_content": "Chapter 1: Introduction\n\nThis chapter covers...",
  "metadata": {
    "source": "manual.pdf",
    "page": 0,
    "page_label": "1",
    "total_pages": 150,
    "document_type": "pdf",
    "processing_engine": "markitdown"
  }
}
```

### PowerPoint Presentations

```json
{
  "page_content": "# Slide Title\n\n- Bullet point 1\n- Bullet point 2",
  "metadata": {
    "source": "presentation.pptx",
    "page": 0,
    "page_label": "1",
    "document_type": "pptx",
    "processing_engine": "markitdown"
  }
}
```

### Excel Spreadsheets

For tabular data, chunk by logical groups (e.g., row ranges):

```json
{
  "page_content": "| Column A | Column B |\n|----------|----------|\n| Value 1 | Value 2 |",
  "metadata": {
    "source": "data.xlsx",
    "page": 0,
    "page_label": "Rows 1-50",
    "document_type": "xlsx",
    "processing_engine": "markitdown"
  }
}
```

## Sub-Chunking Behavior

Open WebUI may further split large documents using its text splitter. When this happens:

1. Original `page` and `page_label` values are preserved
2. `start_index` is added indicating character offset within the original chunk
3. Position can be reconstructed: `page` + `start_index`

### Example Sub-Chunking

Original from external loader:
```json
{
  "page_content": "Very long page content that exceeds chunk size...",
  "metadata": {
    "source": "document.pdf",
    "page": 5,
    "page_label": "6"
  }
}
```

After Open WebUI sub-chunking:
```json
[
  {
    "page_content": "Very long page content...",
    "metadata": {
      "source": "document.pdf",
      "page": 5,
      "page_label": "6",
      "start_index": 0
    }
  },
  {
    "page_content": "...that exceeds chunk size...",
    "metadata": {
      "source": "document.pdf",
      "page": 5,
      "page_label": "6",
      "start_index": 1024
    }
  }
]
```

## Configuration

Set the external loader URL in Open WebUI:

```
Admin Settings > Documents > Document Read Service URL
```

Example: `http://localhost:8000`

## Error Handling

### HTTP Status Codes

| Code | Meaning | Response |
|------|---------|----------|
| 200 | Success | JSON array of documents |
| 400 | Bad Request | `{"error": "Invalid file format"}` |
| 413 | Payload Too Large | `{"error": "File exceeds size limit"}` |
| 415 | Unsupported Media Type | `{"error": "Cannot process this file type"}` |
| 500 | Server Error | `{"error": "Processing failed: reason"}` |

### Empty Documents

If a page has no extractable content, you may either:
- Omit it from the response
- Include it with empty `page_content` (not recommended)

## Implementation Checklist

When building an external loader, ensure:

- [ ] Endpoint accepts PUT requests at `/process`
- [ ] Response is valid JSON array
- [ ] Each document has `page_content` (string) and `metadata` (object)
- [ ] `source` field contains filename
- [ ] `page` field is 0-indexed integer
- [ ] `page_label` provides human-readable label
- [ ] `document_type` indicates file format
- [ ] `processing_engine` identifies your loader
- [ ] Empty pages handled appropriately
- [ ] Error responses include descriptive messages

## Reference Implementations

- [markitdown_service](https://github.com/your-org/markitdown_service) - Example external loader using Microsoft's MarkItDown
- [Mistral OCR loader](../retrieval/loaders/mistral.py) - Internal loader following same conventions

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-10 | Initial specification with 0-based page indexing |
