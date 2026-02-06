# Open WebUI Knowledge Retrieval - Codebase Exploration PRP

**Generated:** 2025-11-26
**Codebase:** https://github.com/open-webui/open-webui
**Version:** v0.6.38
**Project ID:** 04217464-b9eb-4652-8310-dbf3a4682a01

---

## Executive Summary

This exploration plan provides a systematic approach to understanding the Open WebUI codebase, focusing on:

- Knowledge base management and RAG query flow during chat
- Tool calling architecture in chat requests
- File upload flow vs knowledge base flow
- UI components for knowledge features
- Testing infrastructure for chat simulation

### Quick Stats

| Metric | Value |
|--------|-------|
| **Architecture** | Full-stack monolith (FastAPI + SvelteKit) |
| **Primary Languages** | Python 3.11+, TypeScript |
| **Backend Framework** | FastAPI 0.118.0 |
| **Frontend Framework** | SvelteKit 2.5.27 / Svelte 5 |
| **Vector Database** | ChromaDB (default), 9 options supported |
| **RAG Framework** | LangChain 0.3.27 |
| **Key Modules** | 6 (retrieval, routers, models, utils, socket, storage) |
| **Exploration Tasks** | 17 created in Archon |

### Additional Focus Areas (Updated)

Based on follow-up requirements, this PRP also covers:
- **Embedding extensibility** - Adding summaries, keywords, custom metadata to chunks
- **Source viewer extensibility** - Why PDFs work better, how to improve other formats
- **Dynamic full-context mode** - Per-knowledge-base vs global settings
- **Configuration architecture** - Admin UI vs env vars, settings propagation issues

---

## 1. Architecture Overview

### High-Level Structure

```
open-webui/
├── backend/open_webui/           # Python FastAPI backend
│   ├── main.py                   # FastAPI application (~83KB)
│   ├── config.py                 # Configuration (~125KB)
│   ├── routers/                  # API route handlers
│   ├── retrieval/                # RAG/search functionality
│   │   ├── utils.py              # Core RAG orchestration (1,300+ lines)
│   │   ├── vector/               # Vector DB abstractions
│   │   │   ├── factory.py        # DB selection factory
│   │   │   └── dbs/              # 9 vector DB implementations
│   │   └── loaders/              # Document parsers
│   ├── models/                   # SQLAlchemy models
│   ├── utils/                    # Helper utilities
│   │   ├── middleware.py         # Chat-RAG integration
│   │   └── task.py               # Template processing
│   └── socket/                   # WebSocket handlers
│
├── src/                          # SvelteKit frontend
│   ├── lib/
│   │   ├── components/           # Svelte components
│   │   │   ├── chat/             # Chat UI
│   │   │   ├── workspace/        # Knowledge management
│   │   │   └── admin/            # Admin panel
│   │   ├── stores/               # Svelte stores
│   │   └── apis/                 # API client functions
│   └── routes/                   # SvelteKit pages
│
├── test/                         # Python tests
└── cypress/                      # E2E tests
```

### RAG Pipeline Flow

```
User Chat Query
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  middleware.py::chat_completion_files_handler()              │
│  - Detects files/knowledge in metadata                       │
│  - Generates search queries via LLM                          │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  retrieval/utils.py::get_sources_from_items()               │
│  - Embeds queries                                            │
│  - Vector search in collections                              │
│  - Optional: Hybrid BM25 + semantic search                   │
│  - Optional: Reranking with cross-encoder                    │
│  - Filters by relevance threshold                            │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  utils/task.py::rag_template()                              │
│  - Formats sources with <source> tags                        │
│  - Injects into RAG_TEMPLATE (Jinja2)                        │
│  - Adds context to system message                            │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  routers/openai.py or ollama.py                             │
│  - Forwards to upstream LLM API                              │
│  - Streams response back to client                           │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
User receives response with [id] citations
```

### Module Map

| Module | Purpose | Key Files | Exploration Priority |
|--------|---------|-----------|---------------------|
| **retrieval/** | RAG pipeline, vector search, embeddings | utils.py, vector/factory.py | HIGH |
| **routers/** | API endpoints | knowledge.py, files.py, retrieval.py | HIGH |
| **utils/** | Middleware, templates | middleware.py, task.py | HIGH |
| **models/** | Database models | files.py, knowledge.py, chats.py | MEDIUM |
| **socket/** | Real-time WebSocket | main.py | LOW |
| **storage/** | File storage backends | provider.py | LOW |

---

## 2. RAG Configuration Reference

### Key Configuration Settings

| Setting | Default | Location | Purpose |
|---------|---------|----------|---------|
| `RAG_TOP_K` | 3 | config.py | Number of documents to retrieve |
| `RAG_RELEVANCE_THRESHOLD` | 0.0 | config.py | Minimum relevance score (0-1) |
| `RAG_TEMPLATE` | (see below) | config.py | Jinja2 template for context injection |
| `RAG_FULL_CONTEXT` | false | config.py | Use full documents vs chunks |
| `RAG_EMBEDDING_MODEL` | varies | config.py | Embedding model name |
| `RAG_EMBEDDING_ENGINE` | "" | config.py | "", "ollama", "openai", "azure_openai" |
| `RAG_RERANKING_ENGINE` | varies | config.py | Reranking model engine |
| `HYBRID_BM25_WEIGHT` | 0.0 | config.py | BM25 weight in hybrid search |
| `ENABLE_RAG_HYBRID_SEARCH` | false | config.py | Enable BM25+vector hybrid |
| `VECTOR_DB` | "chroma" | config.py | Vector database backend |

### Default RAG Template

```
### Task:
Respond to the user query using the provided context, incorporating inline
citations in the format [id] **only when the <source> tag includes an explicit
id attribute** (e.g., <source id="1">).

### Guidelines:
- If you don't know the answer, clearly state that.
- If uncertain, ask the user for clarification.
- Respond in the same language as the user's query.
- If the context is unreadable or of poor quality, inform the user.
- If the answer isn't present in the context but you possess the knowledge,
  explain this to the user and provide the answer.
- **Only include inline citations using [id] (e.g., [1], [2]) when the
  <source> tag includes an id attribute.**
- Do not cite if the <source> tag does not contain an id attribute.
- Do not use XML tags in your response.
- Ensure citations are concise and directly related to the information provided.

### Output:
Provide a clear and direct response to the user's query, including inline
citations in the format [id] only when the <source> tag with id attribute is
present in the context.

<context>
{{CONTEXT}}
</context>
```

### API Endpoints for Configuration

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/retrieval/config` | GET | Get current RAG config |
| `/api/v1/retrieval/config/update` | POST | Update RAG config (admin) |
| `/api/v1/retrieval/query/settings` | GET/POST | Query settings (k, threshold) |
| `/api/v1/retrieval/embedding` | GET/POST | Embedding config |
| `/api/v1/retrieval/reranking` | GET/POST | Reranking config |

---

## 3. Entry Points & Data Flows

### Chat Message Flow

```
Frontend (SvelteKit)
├── src/routes/(app)/c/[id]/+page.svelte
│   └── Chat.svelte component
│       └── MessageInput.svelte
│           └── POST /openai/chat/completions
                    │
Backend (FastAPI)     │
├── routers/openai.py ◄┘
│   └── generate_chat_completion()
│       ├── Extract metadata (chat_id, collections)
│       ├── Resolve model → base_model_id
│       ├── Apply system prompt + RAG context
│       └── Forward to upstream LLM API
│
├── utils/middleware.py
│   └── chat_completion_files_handler()
│       ├── Generate search queries
│       ├── Call get_sources_from_items()
│       └── Inject context via rag_template()
│
└── retrieval/utils.py
    └── get_sources_from_items()
        ├── Embed queries
        ├── Vector search
        ├── Rerank (optional)
        └── Filter by threshold
```

### File Upload Flow

```
User uploads file
        │
        ▼
POST /api/v1/files/
├── Validate file type & size
├── Store file in UPLOAD_DIR
├── Create FileModel (status="pending")
└── Queue background task
        │
        ▼
Background Processing
├── Detect content type
├── For audio/video: Transcribe via STT
├── For documents: Extract text
└── Call process_file()
        │
        ▼
retrieval.process_file()
├── Load document content
├── Split into chunks (TokenTextSplitter)
├── Generate embeddings
├── Insert into vector DB
└── Update FileModel (status="ready")
```

### Knowledge Base Flow

```
Create Knowledge Base
POST /api/v1/knowledge/create
├── Create Knowledge record
└── Create vector collection
        │
        ▼
Add Files to Knowledge Base
POST /api/v1/knowledge/{id}/file/add
├── Associate file with knowledge
├── Process file if not already processed
└── Add to knowledge collection
        │
        ▼
Query Knowledge Base
(During chat via metadata.collection_names)
├── Resolve collection names
├── Query each collection
└── Merge and rank results
```

---

## 4. UI Components Map

### Admin Panel Structure

```
src/routes/(app)/admin/settings/[tab]/
└── Settings.svelte (wrapper)
    ├── general → General.svelte
    ├── connections → Connections.svelte
    ├── models → Models.svelte
    ├── documents → Documents.svelte  ◄── RAG SETTINGS
    ├── web → WebSearch.svelte
    ├── code-execution → CodeExecution.svelte
    ├── interface → Interface.svelte
    ├── audio → Audio.svelte
    ├── images → Images.svelte
    ├── pipelines → Pipelines.svelte
    ├── evaluations → Evaluations.svelte
    └── db → Database.svelte
```

### Documents.svelte (RAG Settings UI)

```
Embedding Configuration
├── Engine selector (ollama, openai, azure_openai)
├── Model selection
├── Batch size input
└── Provider credentials

Query Settings
├── RAG template (textarea)
├── k: top-k results (default: 4)
├── k_reranker: reranker top-k
├── r: relevance threshold (default: 0.0)  ◄── KEY SETTING
└── hybrid: enable hybrid search

Reranking Configuration
└── Model selector

Global RAG Config
├── PDF_EXTRACT_IMAGES
├── Chunk settings (size, overlap)
├── Content extraction engine
└── YouTube config

Action Buttons
├── Reset Vector DB
├── Reset Upload Directory
└── Reindex Knowledge Files
```

### Chat UI Components

```
src/lib/components/chat/
├── Chat.svelte (main container)
├── MessageInput/
│   ├── MessageInput.svelte
│   └── InputMenu/
│       └── Knowledge.svelte  ◄── Knowledge selector dropdown
├── Messages/
│   ├── Messages.svelte
│   ├── ResponseMessage.svelte
│   └── Citations.svelte  ◄── Source display
└── ChatControls.svelte
```

### Knowledge Workspace Components

```
src/lib/components/workspace/Knowledge/
├── Knowledge.svelte (list view)
├── CreateKnowledgeBase.svelte
├── KnowledgeBase.svelte (detail/editor)
│   ├── AddContentMenu.svelte
│   └── Files.svelte
└── ItemMenu.svelte
```

### Svelte Stores

| Store | Location | Purpose |
|-------|----------|---------|
| `knowledge` | stores/index.ts | Knowledge base list |
| `config` | stores/index.ts | Backend configuration |
| `user` | stores/index.ts | Current user + permissions |
| `settings` | stores/index.ts | User settings |

---

## 5. Questions to Answer

### From INITIAL.md (Original)

#### Retrieval Logic
1. Where is the relevance threshold for RAG results set?
   - **Answer:** `config.py::RAG_RELEVANCE_THRESHOLD` (default 0.0)
2. Can retrieval be skipped entirely if relevance is too low?
   - **Needs exploration:** Check `RerankCompressor` behavior
3. How many sources are returned and is this configurable?
   - **Answer:** `RAG_TOP_K` (default 3), configurable via admin panel
4. Where does the "always include sources" behavior come from?
   - **Needs exploration:** Check `middleware.py` source handling

#### Context Resolution
5. How does the system distinguish "use this specific file" from "search knowledge base"?
   - **Needs exploration:** Check metadata handling in middleware
6. How are recently uploaded files tracked in chat context?
   - **Needs exploration:** Check chat metadata structure
7. Why does "this file" reference resolution fail?
   - **Needs exploration:** Likely no context tracking implemented

#### Retrieval Modes
8. Where is the retrieval-vs-full-context decision made?
   - **Answer:** `RAG_FULL_CONTEXT` config setting
9. How are document summaries stored (if at all)?
   - **Needs exploration:** Likely not implemented
10. Can full-context mode be enabled for knowledge base documents?
    - **Needs exploration:** Check current limitation

#### Tool Calling
11. What triggers tool use vs direct response?
    - **Answer:** Model returns `tool_calls` in response
12. How is the RAG tool registered and invoked?
    - **Needs exploration:** RAG appears to be middleware, not a tool
13. Where is the decision made to call knowledge retrieval?
    - **Answer:** Presence of files/knowledge in metadata

#### UI Components
14. What Svelte components render knowledge/retrieval UI in chat?
    - **Answer:** `InputMenu/Knowledge.svelte`, `Citations.svelte`
15. What's the admin panel component structure for adding new settings?
    - **Answer:** `Settings/Documents.svelte` pattern
16. How do frontend settings sync with backend config?
    - **Answer:** API calls on mount, reactive stores
17. Where are knowledge base management components located?
    - **Answer:** `src/lib/components/workspace/Knowledge/`

#### Testing
18. How are chat interactions tested?
    - **Needs exploration:** Check test/ and cypress/ directories
19. Is there a way to mock knowledge retrieval for testing?
    - **Needs exploration:** Check existing fixtures
20. What test fixtures exist for RAG scenarios?
    - **Needs exploration:** Likely limited

### Discovered During Exploration

1. **ChromaDB Distance Metric:** Default is L2 (Euclidean), not Cosine - potential 30-50% relevance loss
2. **Citation ID Assignment:** How are explicit `id` attributes assigned to sources?
3. **Query Generation Model:** What model generates search queries? Configurable?
4. **Multitenancy:** How are users isolated in multi-tenant deployments?
5. **Caching:** Is there query/embedding caching beyond vector DB?

---

## 6. Exploration Tasks

### Created in Archon (Priority Order)

| # | Task | Focus Area | Priority | Status |
|---|------|------------|----------|--------|
| 1 | Explore: RAG Pipeline Core (retrieval/utils.py) | RAG | 100 | Todo |
| 2 | Explore: Chat-RAG Integration (middleware.py) | RAG | 95 | Todo |
| 3 | Explore: RAG Configuration (config.py) | RAG | 90 | Todo |
| 4 | Explore: Knowledge Base Router (knowledge.py) | RAG | 85 | Todo |
| 5 | Explore: File Upload Pipeline (files.py) | RAG | 80 | Todo |
| 6 | Explore: Admin RAG Settings UI (Documents.svelte) | UI | 75 | Todo |
| 7 | Explore: Knowledge Selection UI (Knowledge.svelte) | UI | 70 | Todo |
| 8 | Explore: Citations Display (Citations.svelte) | UI | 65 | Todo |
| 9 | Explore: Vector DB Factory (factory.py) | RAG | 60 | Todo |
| 10 | Explore: Tool Calling Flow (tools.py, functions.py) | Tool | 55 | Todo |
| 11 | Explore: Testing Infrastructure (test/, cypress/) | Testing | 50 | Todo |

### Recommended Exploration Order

**Phase 1: Core RAG Understanding (Tasks 1-5)**
1. **Start Here:** `backend/open_webui/retrieval/utils.py`
   - Understand the complete retrieval pipeline
   - Map function call flow
   - Note configuration touchpoints

2. **Then:** `backend/open_webui/utils/middleware.py`
   - Understand chat-RAG integration point
   - Find "always include sources" behavior
   - Trace query generation

3. **Next:** `backend/open_webui/config.py`
   - Map all RAG settings
   - Understand PersistentConfig pattern
   - Note default values

4. **Continue:** Knowledge and file routers
   - Understand lifecycle management
   - Map API endpoints

**Phase 2: UI Understanding (Tasks 6-8)**
5. **Admin Panel:** `Documents.svelte`
   - Understand settings UI pattern
   - Note validation approach
   - Plan new settings addition

6. **Chat UI:** Knowledge selection and citations
   - Understand component integration
   - Plan relevance display enhancement

**Phase 3: Deep Dives (Tasks 9-11)**
7. **Vector DB:** Factory pattern and ChromaDB config
8. **Tools:** Tool calling architecture
9. **Testing:** Existing test patterns

---

## 7. Key Files Reference

### Backend (Python)

| File | Lines | Purpose | Read Priority |
|------|-------|---------|---------------|
| `retrieval/utils.py` | ~1,300 | RAG orchestration | MUST READ |
| `utils/middleware.py` | ~1,500 | Chat-RAG integration | MUST READ |
| `config.py` | ~3,000 | All configuration | MUST READ |
| `routers/knowledge.py` | ~500 | Knowledge API | HIGH |
| `routers/files.py` | ~600 | File upload API | HIGH |
| `routers/retrieval.py` | ~2,400 | Retrieval API | HIGH |
| `retrieval/vector/factory.py` | ~200 | Vector DB selection | MEDIUM |
| `retrieval/vector/dbs/chroma.py` | ~300 | ChromaDB implementation | MEDIUM |
| `routers/tools.py` | ~400 | Tool management | MEDIUM |
| `functions.py` | ~300 | Function calling | MEDIUM |
| `utils/task.py` | ~400 | Template processing | MEDIUM |

### Frontend (TypeScript/Svelte)

| File | Purpose | Read Priority |
|------|---------|---------------|
| `admin/Settings/Documents.svelte` | RAG admin settings | MUST READ |
| `chat/MessageInput/InputMenu/Knowledge.svelte` | Knowledge selector | HIGH |
| `chat/Messages/Citations.svelte` | Source display | HIGH |
| `workspace/Knowledge/KnowledgeBase.svelte` | KB management | MEDIUM |
| `lib/apis/knowledge/index.ts` | Knowledge API client | MEDIUM |
| `lib/apis/retrieval/index.ts` | Retrieval API client | MEDIUM |
| `lib/stores/index.ts` | State management | MEDIUM |

---

## 8. Technology Quick Reference

### Backend Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| FastAPI | 0.118.0 | Web framework |
| SQLAlchemy | 2.0.38 | ORM |
| ChromaDB | latest | Vector database (default) |
| LangChain | 0.3.27 | RAG framework |
| sentence-transformers | latest | Embeddings |
| Uvicorn | 0.37.0 | ASGI server |

### Frontend Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| SvelteKit | 2.5.27 | Meta-framework |
| Svelte | 5.x | UI framework |
| TailwindCSS | 4.0.0 | Styling |
| Vite | 5.4.14 | Build tool |
| TypeScript | latest | Type safety |

### Vector DB Options

| Database | Config Value | Notes |
|----------|--------------|-------|
| ChromaDB | "chroma" | Default, in-process |
| Qdrant | "qdrant" | Multitenancy support |
| Milvus | "milvus" | Cloud-native |
| pgvector | "pgvector" | PostgreSQL extension |
| OpenSearch | "opensearch" | Full-text + vector |
| Elasticsearch | "elasticsearch" | Full-text + vector |
| Pinecone | "pinecone" | Managed service |
| Weaviate | "weaviate" | GraphQL interface |
| Oracle 23ai | "oracle23ai" | Enterprise |

---

## 9. Research Findings Summary

### Critical Issue: ChromaDB Distance Metric

**Issue:** ChromaDB defaults to L2 (Euclidean) distance, not Cosine
**Impact:** 30-50% relevance degradation for text similarity
**Fix:** Configure `{"hnsw:space": "cosine"}` when creating collections
**Effort:** 2-4 hours to migrate existing collections

### Top Implementation Recommendations

1. **Configure Cosine Distance** (2-4 hours)
   - Change from L2 to Cosine in ChromaDB
   - Impact: 30-50% relevance improvement

2. **Enable Relevance Filtering** (2-3 hours)
   - Use existing `RAG_RELEVANCE_THRESHOLD` effectively
   - Default is 0.0 (no filtering) - should be 0.5-0.6

3. **Add Dynamic Context Windowing** (4-6 hours)
   - Adjust k-value based on query complexity
   - Prevent token limit violations

4. **Implement Two-Stage Retrieval** (8-12 hours)
   - Summary-based document selection
   - Full document inclusion for selected docs

5. **Add Context Reference Resolution** (8-12 hours)
   - Track recent file uploads in chat context
   - Parse "this file" references
   - Prioritize recent uploads

---

## 10. Embedding & Document Processing Extensibility

### Current Document-to-Embedding Pipeline

```
Document Upload → Content Extraction → Text Splitting → Metadata Assembly → Embedding → Vector DB
```

### Content Extraction Engines (Configurable via `CONTENT_EXTRACTION_ENGINE`)

| Engine | Config Value | Notes |
|--------|--------------|-------|
| Default | "" | PyPDFLoader, CSVLoader, Docx2txtLoader |
| External API | "external" | Custom extraction service |
| Tika | "tika" | External Tika server |
| Docling | "docling" | Advanced document parsing |
| **Azure Document Intelligence** | "document_intelligence" | **Currently in use** |
| MinerU | "mineru" | PDF-specific |
| Mistral OCR | "mistral_ocr" | OCR-based |

### Text Splitting Strategies (`TEXT_SPLITTER` config)

| Strategy | Config Value | Best For |
|----------|--------------|----------|
| Character | "character" | Generic text |
| Token | "token" | LLM-optimized (tiktoken) |
| **Markdown Header** | "markdown_header" | Preserves document structure, extracts headings |

### Current Metadata Schema (Per Chunk)

```python
{
    "name": "filename.pdf",           # Filename
    "source": "path/or/url",          # Source location
    "title": "Document Title",        # If available
    "headings": ["H1", "H2"],         # Section hierarchy (markdown splitter only)
    "file_id": "uuid",                # Reference to file record
    "created_by": "user_id",          # Owner
    "content_type": "application/pdf", # MIME type
    "hash": "sha256...",              # For deduplication
    "embedding_config": {             # Embedding details
        "engine": "azure_openai",
        "model": "text-embedding-ada-002"
    }
}
```

### Vector DB Storage Capabilities

**ChromaDB (Current):**
- Stores: `id`, `text`, `vector`, `metadata` (arbitrary dict)
- Limitation: Large fields auto-filtered (content, pages, tables, figures)
- Query filters: Basic equality only

**PgVector (Alternative):**
- Stores: Same + JSONB support for complex queries
- Advantage: Full SQL filtering on metadata
- Schema extensible with custom columns

### Extension Points for Adding Summaries/Keywords

**Location 1: During Text Splitting** (`routers/retrieval.py` lines 1414-1424)
```python
# BEFORE embedding, enhance metadata
for idx, doc in enumerate(docs):
    doc.metadata.update({
        "summary": generate_summary(doc.page_content),
        "keywords": extract_keywords(doc.page_content),
        "chunk_importance": calculate_importance(doc.page_content),
    })
```

**Location 2: Custom Loader** (`retrieval/loaders/main.py`)
```python
class EnhancedLoader:
    def load(self) -> list[Document]:
        return [Document(
            page_content=content,
            metadata={
                "summary": extract_summary(content),
                "keywords": extract_keywords(content),
                "entities": extract_entities(content),
            }
        )]
```

**Location 3: Pre-embedding Batch Processing**
```python
# Batch generate summaries/keywords for efficiency
texts = [doc.page_content for doc in docs]
summaries = generate_summaries_batch(texts)
keywords_batch = extract_keywords_batch(texts)

metadatas = [
    {
        **doc.metadata,
        "summary": summaries[idx],
        "keywords": keywords_batch[idx],
    }
    for idx, doc in enumerate(docs)
]
```

### Recommended Embedding Enhancements

| Enhancement | Effort | Impact | Implementation |
|-------------|--------|--------|----------------|
| **Add Keywords** | 2-4 hours | Medium | KeyBERT or zero-shot classification |
| **Add Summaries** | 4-6 hours | High | LLM-based or extractive summarization |
| **Named Entity Extraction** | 2-3 hours | Medium | spaCy or transformers NER |
| **Language Detection** | 1 hour | Low | langdetect library |
| **Reading Level** | 1 hour | Low | textstat library |

### Enriched Retrieval (BM25 Hybrid)

Current enrichment in `retrieval/utils.py` lines 169-204:
```python
def get_enriched_texts(collection_result):
    # Already enriches with: filename, title, headings, source, snippet
    # Can add: summary, keywords for better BM25 matching
```

---

## 11. Source Viewer & Citation Display

### Component Architecture

```
ResponseMessage.svelte (Parent)
├── ContentRenderer.svelte
│   └── Markdown → SourceToken.svelte → Source.svelte (inline badge)
├── Citations.svelte (Floating citation summary)
│   ├── CitationsModal.svelte (All citations list)
│   └── CitationModal.svelte (Individual source detail)
└── FileItem.svelte → FileItemModal.svelte (File preview)
```

### Why PDFs Work Better Than Other Formats

| Aspect | PDF | Other Formats |
|--------|-----|---------------|
| **Text Extraction** | PDF.js with page-aware parsing | Generic FileReader.readAsText() |
| **Preview** | Dual: text content + iframe visual | Text only or raw HTML |
| **Page Numbers** | Tracks page metadata | No location tracking |
| **Structure** | Preserves layout awareness | Flat text dump |
| **Library** | Dedicated pdfjs-dist v5.4.149 | No specialized libraries |

### File Type Handling in FileItemModal.svelte

| Type | Extensions | Rendering | Quality |
|------|------------|-----------|---------|
| **PDF** | .pdf | iframe + extracted text | Excellent |
| **Audio** | .mp3, .wav, .ogg, .m4a, .webm | HTML5 `<audio>` | Good |
| **Text** | .txt, .md, .csv, .json, .js, .ts, .css, .html, .xml, .yaml | `<pre>` whitespace-pre-wrap | Basic |
| **Collections** | N/A | Metadata list only | Minimal |

### Extension Points for Better Non-PDF Support

**1. Add File Type Handler** (`FileItemModal.svelte` lines 242-257)
```svelte
{:else if isWordDoc(item.type)}
    <WordDocViewer {item} />
{:else if isExcelSheet(item.type)}
    <ExcelViewer {item} />
{:else if isMarkdown(item.type)}
    <MarkdownRenderer content={textContent} />
```

**2. Add Relevance Display** (`CitationModal.svelte` lines 26-34)
```typescript
// Current color coding by relevance percentage
function getRelevanceColor(percentage: number) {
    if (percentage >= 80) return "green";
    if (percentage >= 60) return "yellow";
    if (percentage >= 40) return "orange";
    return "red";
}
```

**3. Enhance Metadata Display** (`CitationModal.svelte` lines 111-119)
```svelte
{#if document.metadata?.summary}
    <div class="summary">{document.metadata.summary}</div>
{/if}
{#if document.metadata?.keywords}
    <div class="keywords">{document.metadata.keywords.join(", ")}</div>
{/if}
```

### Key Files for Source Viewer Modifications

| Task | File | Lines |
|------|------|-------|
| New file type preview | `FileItemModal.svelte` | 242-257 |
| Change relevance colors | `CitationModal.svelte` | 26-34 |
| Modify citation grouping | `Citations.svelte` | 77-122 |
| Enhance metadata display | `CitationModal.svelte` | 111-119 |
| Update source link handling | `CitationModal.svelte` | 78-89 |
| Change inline badge style | `Source.svelte` | 36-47 |

---

## 12. Dynamic Full-Context Mode

### Current Implementation

**Global Setting:** `RAG_FULL_CONTEXT` in config.py
- Default: `false`
- Storage: PersistentConfig (database + env var fallback)
- Scope: **Global only** - applies to all knowledge bases

**Current Logic** (middleware.py lines 1018-1019):
```python
# Per-file override exists!
all_full_context = all(item.get("context") == "full" for item in files)
full_context = all_full_context or request.app.state.config.RAG_FULL_CONTEXT
```

### Flexibility Analysis

| Level | Currently Supported | Notes |
|-------|---------------------|-------|
| Global | Yes | `RAG_FULL_CONTEXT` setting |
| Per-Knowledge-Base | **No** | `meta` field available but unused |
| Per-File | Yes | `context: "full"` in file item |
| Per-Query | No | Would need API change |

### Knowledge Base Model (models/knowledge.py)

```python
class Knowledge(Base):
    id = Column(Text, primary_key=True)
    data = Column(JSON)           # Currently: {"file_ids": [...]}
    meta = Column(JSON)           # AVAILABLE - currently unused!
    access_control = Column(JSON)
```

### Implementation Plan: Per-Knowledge-Base Full Context

**Step 1: Use `meta` field for retrieval settings**
```python
# In knowledge base creation/update
meta = {
    "retrieval_settings": {
        "full_context": True,      # Per-KB override
        "relevance_threshold": 0.6, # Per-KB threshold
        "top_k": 5                  # Per-KB limit
    }
}
```

**Step 2: Modify retrieval logic** (`retrieval/utils.py`)
```python
def get_sources_from_items(...):
    for item in items:
        kb = Knowledges.get_knowledge_by_id(item.get("id"))
        kb_settings = kb.meta.get("retrieval_settings", {}) if kb.meta else {}

        full_context = (
            item.get("context") == "full" or           # Per-file
            kb_settings.get("full_context", False) or  # Per-KB
            request.app.state.config.RAG_FULL_CONTEXT  # Global
        )
```

**Step 3: Add UI in Knowledge Base editor**
- Toggle for "Use full document context"
- Optional: relevance threshold slider
- Optional: top-k override

### Key Files for Dynamic Full Context

| File | Lines | Change |
|------|-------|--------|
| `models/knowledge.py` | 28-76 | Document meta schema |
| `routers/knowledge.py` | create/update | Accept retrieval_settings in meta |
| `retrieval/utils.py` | 920-1132 | Check KB settings before global |
| `middleware.py` | 1018-1019 | Pass KB settings through |

---

## 13. Configuration Architecture & Settings Propagation

### 3-Tier Configuration System

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: Environment Variables (env.py)                        │
│  - Loaded at startup from .env file                            │
│  - Infrastructure settings (DATABASE_URL, REDIS_URL, etc.)     │
│  - NOT modifiable at runtime                                    │
│  - Highest priority for infrastructure-critical settings        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: Database (PersistentConfig in config.py)             │
│  - SQLite/PostgreSQL table: `config` with JSON column          │
│  - Admin-configurable settings                                  │
│  - Auto-loaded at startup via get_config()                     │
│  - Can be updated dynamically without restart                   │
│  - REQUIRES: ENABLE_PERSISTENT_CONFIG=true                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 3: Runtime Memory (AppConfig class)                     │
│  - FastAPI app state: app.state.config                         │
│  - Mirrors database values for fast access                     │
│  - Optional Redis caching for distributed deployments          │
│  - Updated when database changes                                │
└─────────────────────────────────────────────────────────────────┘
```

### PersistentConfig Pattern

```python
class PersistentConfig(Generic[T]):
    def __init__(self, env_name: str, config_path: str, env_value: T):
        self.env_name = env_name        # "RAG_TOP_K"
        self.config_path = config_path  # "rag.top_k"
        self.env_value = env_value      # Default from env var

        # Check database for override
        self.config_value = get_config_value(config_path)

        # Use database if ENABLE_PERSISTENT_CONFIG=true
        if self.config_value is not None and ENABLE_PERSISTENT_CONFIG:
            self.value = self.config_value
        else:
            self.value = env_value
```

### Admin UI vs Environment Variables

**Admin-Configurable (Database + API):**
- RAG settings (top_k, relevance_threshold, template, etc.)
- Embedding/reranking configuration
- OAuth providers (if ENABLE_OAUTH_PERSISTENT_CONFIG=true)
- API keys settings
- Default models, model order
- Code execution engines
- Web search settings
- UI banners and suggestions

**Environment-Only (Not in Admin):**
- `DATABASE_URL`, `DATABASE_USER`, `DATABASE_PASSWORD`
- `REDIS_URL`, `REDIS_CLUSTER`
- `WEBUI_SECRET_KEY`
- `USE_CUDA_DOCKER`, `DEVICE_TYPE`
- `GLOBAL_LOG_LEVEL`
- OpenTelemetry settings
- License key/blob

### Settings Propagation Issues & Fixes

| Problem | Root Cause | Fix |
|---------|------------|-----|
| Settings don't take effect | `ENABLE_PERSISTENT_CONFIG=false` | Set to `true` |
| Changes lost after restart | Not saved to database | Ensure endpoints call `save_config()` |
| Multi-instance inconsistency | No Redis sync | Configure `REDIS_URL` |
| OAuth settings not loading | `ENABLE_OAUTH_PERSISTENT_CONFIG=false` | Set to `true` |
| Stale values after update | Cached old value | Use `request.app.state.config.X` |

### Extension Plan: Env Var Viewer in Admin

**Security Considerations:**
- Many env vars contain sensitive data (API keys, passwords)
- Must filter or mask sensitive values
- Admin-only access

**Safe Implementation:**
```python
# In routers/configs.py
SAFE_ENV_VARS = [
    "ENV", "DEVICE_TYPE", "OFFLINE_MODE", "WEBUI_NAME",
    "VERSION", "GLOBAL_LOG_LEVEL", "ENABLE_PERSISTENT_CONFIG"
]

SENSITIVE_PATTERNS = ["API_KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL"]

@router.get("/env/status")
async def get_env_status(user=Depends(get_admin_user)):
    return {
        "public": {var: os.environ.get(var) for var in SAFE_ENV_VARS if var in os.environ},
        "configured": [var for var in os.environ if not any(s in var for s in SENSITIVE_PATTERNS)],
        "secure_count": len([var for var in os.environ if any(s in var for s in SENSITIVE_PATTERNS)])
    }
```

### Key Files for Configuration

| File | Purpose |
|------|---------|
| `config.py` | PersistentConfig, AppConfig, all settings |
| `env.py` | Environment variable loading |
| `models/configs.py` | Database config storage |
| `routers/configs.py` | Config API endpoints |
| `main.py` lines 653-776 | Config initialization |

---

## 14. Updated Exploration Tasks

### New Tasks Added to Archon

| # | Task | Focus Area | Priority | Status |
|---|------|------------|----------|--------|
| 12 | Explore: Embedding Metadata Extension Points | Embedding | 95 | Todo |
| 13 | Explore: Source Viewer Components (PDF vs Others) | UI | 85 | Todo |
| 14 | Explore: Knowledge Base Meta Field Usage | RAG | 80 | Todo |
| 15 | Explore: PersistentConfig & Settings Propagation | Config | 75 | Todo |
| 16 | Implement: Per-KB Full Context Toggle | Feature | 70 | Todo |
| 17 | Implement: Env Var Viewer in Admin Panel | Feature | 65 | Todo |

---

## 15. Next Steps

### Immediate (This Session)

1. Review this PRP for completeness
2. Start with Task #1: RAG Pipeline Core exploration
3. Update Serena memories with findings

### Short-term (This Week)

1. Complete Phase 1 exploration tasks (1-5)
2. Document answers to open questions
3. Create implementation PRPs for target additions

### Medium-term (Next Sprint)

1. Complete Phase 2 UI exploration (6-8)
2. Implement relevance-based filtering
3. Add relevance threshold to admin UI

### Long-term (Future Sprints)

1. Smart full-context mode implementation
2. Better context resolution
3. Chat simulation test harness

---

## Appendix A: Subagent Execution Summary

### Subagents Executed

| Subagent | Purpose | Key Findings |
|----------|---------|--------------|
| Explore (RAG) | Architecture analysis | Complete RAG pipeline map, 1,300+ line utils.py |
| Explore (UI) | Component mapping | Admin panel structure, Svelte patterns |
| Explore (Flow) | Entry points | Chat → RAG flow, file upload pipeline |
| Technical Researcher | Best practices | ChromaDB gotchas, LangChain patterns |

### Research Documents Generated

1. **RAG Pipeline Overview** - Complete flow from query to response
2. **Configuration Reference** - All settings with defaults
3. **UI Component Map** - Frontend structure for knowledge features
4. **API Endpoint Reference** - All relevant REST endpoints
5. **Best Practices Research** - 50+ gotchas, implementation patterns

---

## Appendix B: Absolute File Paths

### Backend Key Files
```
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\retrieval\utils.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\utils\middleware.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\config.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\routers\knowledge.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\routers\files.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\routers\retrieval.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\retrieval\vector\factory.py
C:\Users\neura\Documents\Repositories\open-webui\backend\open_webui\retrieval\vector\dbs\chroma.py
```

### Frontend Key Files
```
C:\Users\neura\Documents\Repositories\open-webui\src\lib\components\admin\Settings\Documents.svelte
C:\Users\neura\Documents\Repositories\open-webui\src\lib\components\chat\MessageInput\InputMenu\Knowledge.svelte
C:\Users\neura\Documents\Repositories\open-webui\src\lib\components\chat\Messages\Citations.svelte
C:\Users\neura\Documents\Repositories\open-webui\src\lib\components\workspace\Knowledge\KnowledgeBase.svelte
C:\Users\neura\Documents\Repositories\open-webui\src\lib\apis\knowledge\index.ts
C:\Users\neura\Documents\Repositories\open-webui\src\lib\apis\retrieval\index.ts
```

---

**End of Exploration PRP**
