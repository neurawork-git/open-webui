# INITIAL: Per-Level RAG Settings Enhancement

## PROJEKT-KONTEXT

### Overall Automation Project
**Open WebUI Enhancement Project** - Improving the RAG (Retrieval-Augmented Generation) system to provide more granular control over retrieval settings.

### This Component's Role
This component introduces **per-level RAG settings** allowing administrators, users, and content managers to customize retrieval behavior at different granularity levels instead of relying solely on global admin settings.

### Integration Points
- **Backend**: `middleware.py`, `retrieval/utils.py`, model/knowledge/user/chat routers
- **Frontend**: Admin settings, Knowledge edit modal, Model edit page, User settings
- **Database**: Utilizes existing `meta` and `settings` JSON fields (no schema migration)
- **Existing Systems**: Builds on current `PersistentConfig` and `AppConfig` architecture

---

## FUNKTIONALE ANFORDERUNGEN

### Core Features

#### F1: Knowledge Collection Level Settings
**Priority: HIGH**
- Allow per-knowledge-base RAG settings via `Knowledge.meta.rag_settings`
- Settings include: `top_k`, `relevance_threshold`, `enable_hybrid_search`, `hybrid_bm25_weight`, `full_context`
- UI in Knowledge edit modal for configuring these settings
- Override global settings when this knowledge base is searched

**User Stories:**
- As a content manager, I want to set a higher relevance threshold (0.8) for my legal documents knowledge base because precision is critical
- As an admin, I want certain knowledge bases to always use full context mode regardless of global settings

**Acceptance Criteria:**
- [ ] Knowledge.meta can store rag_settings object
- [ ] KnowledgeForm includes meta field for API updates
- [ ] Knowledge edit UI shows RAG settings section
- [ ] Settings are read and applied in retrieval pipeline
- [ ] Falls back to global settings when not specified

#### F2: Model Level Settings
**Priority: MEDIUM**
- Allow per-model RAG settings via `Model.meta.rag_settings`
- When a model is selected, its RAG settings override global defaults
- UI in Model configuration page

**User Stories:**
- As an admin, I want my "Research Assistant" model to retrieve more documents (top_k=10) than default
- As a user, I want the "Precise Answers" model to use stricter relevance filtering

**Acceptance Criteria:**
- [ ] Model.meta can store rag_settings object
- [ ] Model edit UI shows RAG settings section
- [ ] Settings are read from model config in middleware
- [ ] Falls back to global settings when not specified

#### F3: User Level Settings
**Priority: MEDIUM**
- Allow per-user RAG preferences via `User.settings.rag_settings`
- Users can set their preferred retrieval behavior
- UI in User Settings page

**User Stories:**
- As a power user, I want to always use hybrid search even if admin has it disabled globally
- As a user who values precision, I want my default relevance threshold to be higher

**Acceptance Criteria:**
- [ ] User.settings can store rag_settings object
- [ ] User settings UI shows RAG preferences section
- [ ] Settings are read from user in middleware
- [ ] Falls back to global settings when not specified

#### F4: Chat Level Settings (Future/Optional)
**Priority: LOW**
- Allow per-chat RAG settings via `Chat.meta.rag_settings`
- Settings applied to specific conversation only
- UI in chat settings modal

**User Stories:**
- As a user, I want this specific research chat to use full context mode
- As a user, I want to temporarily increase top_k for a complex investigation

**Acceptance Criteria:**
- [ ] Chat.meta can store rag_settings object
- [ ] Chat settings UI shows RAG options
- [ ] Settings passed through request metadata
- [ ] Falls back to model/user/global settings

#### F5: Settings Priority Cascade
**Priority: HIGH**
- Implement merge logic with clear priority order
- Priority (highest to lowest): Knowledge > Chat > Model > User > Global
- Partial overrides supported (only override specific fields)

**Acceptance Criteria:**
- [ ] Merge function correctly combines settings from all levels
- [ ] Higher priority settings override lower priority
- [ ] Unset fields fall back to next level
- [ ] All RAG-related settings supported in cascade

### Settings Schema

```typescript
interface RagSettings {
  top_k?: number;                    // Number of chunks to retrieve (1-20)
  top_k_reranker?: number;           // Results after reranking (1-20)
  relevance_threshold?: number;      // Minimum score filter (0.0-1.0)
  enable_hybrid_search?: boolean;    // Enable BM25+Vector hybrid
  hybrid_bm25_weight?: number;       // BM25 weight in hybrid (0.0-1.0)
  full_context?: boolean;            // Bypass retrieval, use full documents
  enable_query_generation?: boolean; // Generate search queries via LLM
}
```

---

## TECHNOLOGIE-STACK

### Backend
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **ORM**: SQLAlchemy
- **Database**: SQLite (default) with JSON field support
- **Validation**: Pydantic models

### Frontend
- **Framework**: SvelteKit with Svelte 5
- **Styling**: TailwindCSS
- **State**: Svelte stores
- **i18n**: i18next

### Existing Infrastructure
- `PersistentConfig` for global settings
- `AppConfig` for runtime state with optional Redis
- JSON columns in all relevant tables (`meta`, `settings`)

---

## ABHANGIGKEITEN

### Prerequisites
- Understanding of current RAG pipeline (`retrieval/utils.py`)
- Familiarity with middleware flow (`utils/middleware.py`)
- Knowledge of existing model structures

### Blocking Relationships
- F5 (Cascade) blocks F1-F4 implementation in middleware
- F1 (Knowledge) should be implemented first as reference pattern
- Frontend components depend on backend API changes

### Integration Dependencies
- No external service dependencies
- No database migration required (uses existing JSON fields)
- Must maintain backward compatibility (empty meta = use globals)

---

## RESSOURCEN

### Team Composition
- 1 Full-stack developer (Python + Svelte)
- Familiarity with Open WebUI codebase helpful

### Effort Estimates
| Feature | Backend | Frontend | Testing | Total |
|---------|---------|----------|---------|-------|
| F1: Knowledge Level | 4h | 4h | 2h | 10h |
| F2: Model Level | 2h | 3h | 1h | 6h |
| F3: User Level | 2h | 3h | 1h | 6h |
| F4: Chat Level | 4h | 4h | 2h | 10h |
| F5: Cascade Logic | 3h | 0h | 2h | 5h |
| Integration Testing | 0h | 0h | 4h | 4h |
| **Total** | **15h** | **14h** | **12h** | **41h** |

### Budget Constraints
- No additional infrastructure costs
- No external API costs
- Development time only

---

## RISIKEN

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Performance impact from fetching settings per-request | Medium | Medium | Cache knowledge/model settings in memory; lazy loading |
| Settings conflicts causing unexpected behavior | Low | High | Clear documentation; UI shows effective settings |
| Breaking existing workflows | Low | High | Backward compatible (empty = global); feature flags |

### Integration Challenges

| Challenge | Mitigation |
|-----------|------------|
| Frontend state management for nested settings | Use dedicated stores per settings level |
| i18n for new settings labels | Add translations incrementally |
| Testing all cascade combinations | Parametrized unit tests for merge logic |

### Unknown Factors
- User adoption and feedback on UI placement
- Whether chat-level settings provide enough value to implement
- Potential need for "lock" feature (admin prevents user overrides)

---

## NICHT-FUNKTIONALE ANFORDERUNGEN

### Performance
- Settings lookup should add < 5ms to request processing
- Consider caching frequently accessed knowledge/model settings

### Security
- Validate all settings values (ranges, types)
- Ensure users cannot override admin-locked settings (future)
- No sensitive data in settings objects

### Maintainability
- Centralized merge function for all settings
- Type definitions shared between backend and frontend
- Clear logging of effective settings for debugging

### Backward Compatibility
- Empty/null meta fields must use global defaults
- Existing API contracts unchanged
- No database migrations required

---

## IMPLEMENTATION PHASES

### Phase 1: Foundation (F5 + F1)
1. Implement settings merge function in middleware
2. Add Knowledge.meta.rag_settings support
3. Create Knowledge settings UI
4. Write unit tests for cascade logic

### Phase 2: Model & User (F2 + F3)
1. Add Model.meta.rag_settings support
2. Add User.settings.rag_settings support
3. Create Model and User settings UI
4. Integration testing

### Phase 3: Chat Level (F4) - Optional
1. Add Chat.meta.rag_settings support
2. Create Chat settings UI
3. Full end-to-end testing

---

## SUCCESS METRICS

- All settings levels function independently
- Cascade priority works correctly in all combinations
- No regression in existing RAG functionality
- UI is intuitive (< 2 clicks to access settings)
- Documentation updated with new capabilities

---

## OPEN QUESTIONS

1. Should admins be able to "lock" certain settings (prevent user/model overrides)?
2. Should there be a UI indicator showing "effective settings" (merged result)?
3. Is Chat-level settings valuable enough to implement in Phase 1?
4. Should we add settings presets/templates for common configurations?
