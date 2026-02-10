# Query Generation Prompt Analysis

## Overview

This document explains how search keywords are generated for hybrid search (BM25 + vector) in Open WebUI's RAG system, and proposes improvements to prevent overly broad keywords like "and", "the", etc. from derailing keyword search.

## Code Flow

### 1. Where Keywords Are Generated

**File:** `backend/open_webui/utils/middleware.py:1753-1776`

When a user sends a message with attached knowledge bases/files, the middleware generates search queries:

```python
queries_response = await generate_queries(
    request,
    {
        "model": body["model"],
        "messages": body["messages"],
        "type": "retrieval",  # <-- Triggers RAG query generation
    },
    user,
)
# Parses JSON response to extract queries list
queries = queries_response.get("queries", [])
```

### 2. Where the Prompt Is Applied

**File:** `backend/open_webui/routers/tasks.py:510-515`

```python
if (request.app.state.config.QUERY_GENERATION_PROMPT_TEMPLATE).strip() != "":
    template = request.app.state.config.QUERY_GENERATION_PROMPT_TEMPLATE
else:
    template = DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE

content = query_generation_template(template, form_data["messages"], user)
```

### 3. Where the Default Prompt Is Defined

**File:** `backend/open_webui/config.py:1885-1907`

### 4. Where It's Configurable

| Method | Location |
|--------|----------|
| Admin UI | Settings → Interface → "Query Generation Prompt" |
| Config key | `QUERY_GENERATION_PROMPT_TEMPLATE` |
| Environment variable | `QUERY_GENERATION_PROMPT_TEMPLATE` |

## Current Default Prompt

```
### Task:
Analyze the chat history to determine the necessity of generating search queries, in the given language. By default, **prioritize generating 1-3 broad and relevant search queries** unless it is absolutely certain that no additional information is required. The aim is to retrieve comprehensive, updated, and valuable information even with minimal uncertainty. If no search is unequivocally needed, return an empty list.

### Guidelines:
- Respond **EXCLUSIVELY** with a JSON object. Any form of extra commentary, explanation, or additional text is strictly prohibited.
- When generating search queries, respond in the format: { "queries": ["query1", "query2"] }, ensuring each query is distinct, concise, and relevant to the topic.
- If and only if it is entirely certain that no useful results can be retrieved by a search, return: { "queries": [] }.
- Err on the side of suggesting search queries if there is **any chance** they might provide useful or updated information.
- Be concise and focused on composing high-quality search queries, avoiding unnecessary elaboration, commentary, or assumptions.
- Today's date is: {{CURRENT_DATE}}.
- Always prioritize providing actionable and broad queries that maximize informational coverage.

### Output:
Strictly return in JSON format:
{
  "queries": ["query1", "query2"]
}

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>
```

### Problems with Current Prompt

1. **"Broad" is too vague** - The instruction to generate "broad" queries can result in generic terms
2. **No stopword guidance** - Nothing prevents the LLM from including common words like "and", "the", "or", "is"
3. **No examples** - No concrete examples of good vs bad queries
4. **Phrase-focused** - Encourages natural language phrases instead of keyword-focused terms

## Proposed Improved Prompt

```
### Task:
Analyze the chat history to generate 1-3 precise search queries for retrieving relevant documents from a knowledge base. Focus on extracting the key concepts, entities, and technical terms that would match document content.

### Guidelines:
- Respond **EXCLUSIVELY** with a JSON object. No commentary or additional text.
- Generate queries in the format: { "queries": ["query1", "query2"] }
- If no search is needed, return: { "queries": [] }

### Query Quality Rules:
- **DO** use specific nouns, proper names, technical terms, and domain-specific vocabulary
- **DO** extract key entities (product names, person names, concepts, technologies)
- **DO** include relevant verbs that describe actions (configure, install, troubleshoot, analyze)
- **DO NOT** include stopwords as standalone terms: and, or, the, a, an, is, are, was, were, be, been, being, have, has, had, do, does, did, will, would, could, should, may, might, must, shall, can, of, in, to, for, with, on, at, by, from, as, into, through, during, before, after, above, below, between, under, again, further, then, once, here, there, when, where, why, how, all, each, every, both, few, more, most, other, some, such, no, nor, not, only, own, same, so, than, too, very, just, also
- **DO NOT** generate vague queries like "information about" or "details on"
- **DO NOT** use filler phrases - every word should be searchable

### Examples:
Good queries:
- "PostgreSQL connection pooling configuration" (specific technical terms)
- "OAuth2 refresh token expiration" (specific concept + technical detail)
- "Python async await error handling" (language + feature + action)

Bad queries:
- "how to configure and set up the database" (contains stopwords, vague)
- "information about authentication" (filler phrase, too broad)
- "the best practices for development" (stopwords, generic)

### Output:
Return strictly as JSON:
{
  "queries": ["specific_query_1", "specific_query_2"]
}

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>
```

## Key Improvements

| Aspect | Current | Proposed |
|--------|---------|----------|
| Guidance | "broad and relevant" | "precise", "key concepts, entities, technical terms" |
| Stopwords | Not mentioned | Explicit list of words to avoid |
| Examples | None | Good and bad examples provided |
| Focus | Natural language phrases | Keyword-focused terms |
| Filler phrases | Not addressed | Explicitly prohibited |

## Implementation Options

### Option A: Update Default Prompt (Code Change)
Modify `DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE` in `backend/open_webui/config.py:1885-1907`

### Option B: Configure via Admin UI (No Code Change)
1. Go to Admin Settings → Interface
2. Find "Query Generation Prompt"
3. Paste the improved prompt

### Option C: Environment Variable
Set `QUERY_GENERATION_PROMPT_TEMPLATE` environment variable with the improved prompt.

## Additional Recommendation: Stopword Filtering

Even with an improved prompt, consider adding stopword filtering in the tokenization function:

**File:** `backend/open_webui/retrieval/utils.py:91-122`

```python
STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
    'has', 'have', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'that',
    'the', 'to', 'was', 'were', 'will', 'with', 'the', 'this', 'but',
    'they', 'which', 'would', 'there', 'their', 'what', 'so', 'up',
    'out', 'if', 'about', 'who', 'get', 'than', 'been', 'can', 'had',
    'her', 'him', 'his', 'how', 'into', 'may', 'no', 'not', 'only',
    'other', 'our', 'should', 'such', 'then', 'these', 'through',
    'under', 'very', 'when', 'where', 'while', 'why', 'you', 'your'
}

def tokenize_for_bm25(text: str) -> list[str]:
    text = text.lower()
    tokens = text.split()
    cleaned = []
    for token in tokens:
        cleaned_token = re.sub(r'^[^\w]+|[^\w]+$', '', token, flags=re.UNICODE)
        if cleaned_token and cleaned_token not in STOPWORDS:  # <-- Add stopword filter
            cleaned.append(cleaned_token)
    return cleaned
```

This provides defense-in-depth: even if the LLM generates queries with stopwords, they won't pollute the BM25 search.

## Related Files

| File | Purpose |
|------|---------|
| `backend/open_webui/config.py:1879-1907` | Prompt configuration and default |
| `backend/open_webui/routers/tasks.py:460-541` | Query generation endpoint |
| `backend/open_webui/utils/middleware.py:1753-1776` | Where queries are generated for RAG |
| `backend/open_webui/utils/task.py:321-329` | Template processing |
| `backend/open_webui/retrieval/utils.py:91-122` | BM25 tokenization |
| `src/lib/components/admin/Settings/Interface.svelte:345-358` | Admin UI for prompt |

---

*Document created: 2026-02-10*
*Related to: Hybrid search keyword quality improvement*
