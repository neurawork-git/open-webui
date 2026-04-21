# BM25 Tokenization Fix - Requirements

## Problem Statement

BM25 hybrid search fails to match relevant documents because tokenization uses simple `text.lower().split()` which keeps punctuation attached to words.

**Example:**
- Query: "Berlin 2025"
- Query tokens: `['berlin', '2025']`
- Document contains: "Berlin, Stadt" (with comma)
- Document tokens: `['berlin,', 'stadt']`
- Result: No match because `'berlin' != 'berlin,'`

## Root Cause

In `backend/open_webui/retrieval/utils.py`, lines 313-315:
```python
tokenized_docs = [doc.lower().split() for doc in bm25_texts]
query_tokens = query.lower().split()
```

This naive tokenization:
1. Keeps punctuation attached to words
2. Doesn't handle German umlauts or special characters
3. Treats "Berlin," and "berlin" as different tokens

## Solution

Replace simple tokenization with a smarter function that:
1. Strips common punctuation from word boundaries
2. Preserves German umlauts (ä, ö, ü, ß)
3. Handles numbers and special table characters

## Implementation

### New Function: `tokenize_for_bm25(text: str) -> list[str]`

```python
import re

def tokenize_for_bm25(text: str) -> list[str]:
    """
    Tokenize text for BM25 scoring with proper punctuation handling.

    - Converts to lowercase
    - Removes punctuation from word boundaries
    - Preserves German umlauts and internal hyphens
    - Filters empty tokens
    """
    # Lowercase
    text = text.lower()

    # Split on whitespace
    tokens = text.split()

    # Strip punctuation from token boundaries
    # Keep internal characters (e.g., hyphenated words)
    cleaned = []
    for token in tokens:
        # Remove leading/trailing punctuation but keep internal
        cleaned_token = re.sub(r'^[^\w]+|[^\w]+$', '', token, flags=re.UNICODE)
        if cleaned_token:
            cleaned.append(cleaned_token)

    return cleaned
```

### Files to Modify

1. `backend/open_webui/retrieval/utils.py`
   - Add `tokenize_for_bm25()` function
   - Replace lines 313-315 to use new function

### Test Cases

1. **Basic punctuation stripping**
   - Input: `"Berlin, Stadt"` → `['berlin', 'stadt']`
   - Input: `"(Hamburg)"` → `['hamburg']`

2. **German text preservation**
   - Input: `"München Düsseldorf"` → `['münchen', 'düsseldorf']`
   - Input: `"Bevölkerung"` → `['bevölkerung']`

3. **Numbers and mixed content**
   - Input: `"10178 | 891.12"` → `['10178', '891.12']`
   - Input: `"3,782,202"` → `['3,782,202']` (internal commas preserved)

4. **Edge cases**
   - Input: `"..."` → `[]`
   - Input: `""` → `[]`
   - Input: `"  multiple   spaces  "` → tokens without empty strings

## Acceptance Criteria

- [x] Query "Berlin" matches document containing "Berlin," ✅
- [x] Query "Bevölkerung Leipzig" matches the German statistics table ✅
- [x] German umlauts preserved in both query and document tokens ✅
- [x] Unit tests cover all cases above ✅ (24 tests passing)
- [x] No regression in existing hybrid search functionality ✅

## Implementation Summary

**Files Modified:**
- `backend/open_webui/retrieval/utils.py` - Added `tokenize_for_bm25()` function and updated BM25 usage

**Files Created:**
- `backend/open_webui/test/retrieval/test_bm25_tokenization.py` - 24 unit tests

**Key Changes:**
1. Added `tokenize_for_bm25(text: str) -> list[str]` function (lines 83-114)
2. Updated manual BM25 scoring to use new tokenization (line 353, 355)
3. Added `preprocess_func=tokenize_for_bm25` to `BM25Retriever.from_texts()` (line 371)

## Timeline

- Implementation: 30 minutes ✅
- Testing: 30 minutes ✅
