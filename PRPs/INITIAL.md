# INITIAL: Open WebUI Knowledge Retrieval Exploration

## EXPLORATION GOALS

- Understand knowledge base management and query flow during chat
- Understand tool calling architecture in chat requests
- Map the RAG pipeline: query → retrieval → context injection → response
- Identify where relevance scoring happens and how it's configured
- Understand file upload flow vs knowledge base flow
- Understand how "recency" and "context references" (like "this file") are handled
- Understand how retrieval/knowledge features are exposed in the UI (chat, admin, knowledge management)
- Map the UI component structure for seamless feature integration
- Map the testing infrastructure for chat simulation

## FOCUS AREAS

### High Priority

1. **RAG/Retrieval Pipeline**
   - How are queries vectorized and matched?
   - Where is the "top K" or relevance threshold set?
   - How does retrieval differ for uploads vs knowledge bases?
   - What vector database is used and how is it configured?

2. **Tool Calling Architecture**
   - How does the system decide to use knowledge vs not?
   - What's the tool calling flow for RAG?
   - How are tools registered and invoked during chat?

3. **File Upload Handling**
   - How are uploads indexed?
   - How does "this file" context resolution work (or fail)?
   - What's the timing between upload and availability for retrieval?

4. **UI Architecture for Knowledge Features**
   - How is knowledge base selection rendered in chat UI?
   - Where are retrieval settings exposed in admin panel?
   - How do file upload UI and knowledge base UI differ?
   - What Svelte components handle these interactions?
   - What's the pattern for adding new settings to admin panel?

### Medium Priority

5. **Admin Configuration System**
   - Where are retrieval settings stored?
   - What's configurable via admin panel?
   - How do backend settings surface to frontend?

6. **Testing Infrastructure**
   - How are chat scenarios tested?
   - Can knowledge retrieval be tested in isolation?
   - How to simulate chat with knowledge context?

## KNOWN CONTEXT

### Deployment Context
- Deployed for enterprise customer as company-internal all-purpose LLM
- Reliability in knowledge retrieval is critical
- Users expect uploaded files and knowledge bases to work seamlessly

### Observed Issues
- Knowledge sources are always included regardless of relevance (even for unrelated queries)
- "This file" and similar context references fail to resolve to recently uploaded files
- No dynamic choice between retrieval mode (chunks) and full-context mode for knowledge bases
- Full-context mode works for single file uploads but not for knowledge base documents

### Tech Stack (from Serena onboarding)
- Backend: FastAPI, SQLAlchemy, ChromaDB (vector store)
- Frontend: SvelteKit, Svelte 5, TailwindCSS
- RAG: LangChain integration, sentence-transformers

## QUESTIONS TO ANSWER

### Retrieval Logic
1. Where is the relevance threshold for RAG results set?
2. Can retrieval be skipped entirely if relevance is too low?
3. How many sources are returned and is this configurable?
4. Where does the "always include sources" behavior come from?

### Context Resolution
5. How does the system distinguish "use this specific file" from "search knowledge base"?
6. How are recently uploaded files tracked in chat context?
7. Why does "this file" reference resolution fail?

### Retrieval Modes
8. Where is the retrieval-vs-full-context decision made?
9. How are document summaries stored (if at all)?
10. Can full-context mode be enabled for knowledge base documents?

### Tool Calling
11. What triggers tool use vs direct response?
12. How is the RAG tool registered and invoked?
13. Where is the decision made to call knowledge retrieval?

### UI Components
14. What Svelte components render knowledge/retrieval UI in chat?
15. What's the admin panel component structure for adding new settings?
16. How do frontend settings sync with backend config?
17. Where are knowledge base management components located?

### Testing
18. How are chat interactions tested?
19. Is there a way to mock knowledge retrieval for testing?
20. What test fixtures exist for RAG scenarios?

## TARGET ADDITIONS

### 1. Relevance-Based Filtering
**Problem:** Sources are always included regardless of relevance to the query.

**Solution:** Admin-configurable relevance threshold to skip low-relevance sources.

- **Backend:**
  - Add relevance threshold config
  - Filter retrieval results below threshold
  - Option to return zero sources if none meet threshold

- **UI:**
  - Admin panel setting (global and/or per-knowledge-base)
  - Possibly show relevance scores in chat UI for transparency

### 2. Smart Full-Context Mode
**Problem:** Knowledge bases only support chunk retrieval, not full document context.

**Solution:** Two-stage retrieval using document summaries to select the right document(s), then include full content.

- **Backend:**
  - Generate/store document summaries on upload
  - First stage: match query against summaries
  - Second stage: include full document(s) that match
  - Configurable threshold for when to use full vs chunks

- **UI:**
  - Toggle or mode selector in knowledge base settings
  - Indicator in chat showing which mode was used

### 3. Better Context Resolution
**Problem:** "This file" and similar references don't resolve to recently uploaded files.

**Solution:** Context-aware retrieval that prioritizes recent uploads and understands references.

- **Backend:**
  - Track file upload order/recency in chat context
  - Parse references like "this file", "the document I uploaded", etc.
  - Prioritize recent uploads when references detected

- **UI:**
  - Visual indicator of which file is being referenced
  - Clearer feedback when files are ready for use

### 4. Chat Simulation Test Harness
**Problem:** Difficult to test specific chat + knowledge scenarios reproducibly.

**Solution:** Test infrastructure for simulating chat situations with controlled knowledge context.

- **Implementation:**
  - Fixtures for chat history with knowledge
  - Mock retrieval results
  - Assertion helpers for source inclusion
  - Integration with existing pytest setup

## CONSTRAINTS & PREFERENCES

### Output Preferences
- [x] Create detailed Serena memories for each module explored
- [ ] Create Notion documentation (optional, later)
- [x] Update Archon tasks with findings
- [x] Map UI components alongside backend logic

### Integration Requirements
- All additions must integrate with existing UI patterns
- Settings should follow existing admin panel conventions
- Must work with existing knowledge base structure (no breaking changes)

### Quality Bar
- Enterprise deployment = high reliability requirements
- Changes must be testable
- Prefer configuration over code changes where possible
