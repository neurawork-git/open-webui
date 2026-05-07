# FORK_CHANGES.md

> **Inventory of every fork-local deviation from upstream.** Regenerate this file after every upstream merge — line numbers drift otherwise. See `.claude/skills/alembic-merge/SKILL.md` Step 8 for regeneration, and the `alembic-merge` skill for the re-apply workflow during conflict resolution.
>
> Categories:
> - **Additive** — new modules / new directories. Zero conflict risk with upstream.
> - **Injection** — 2–10 line hooks into upstream hotspots. Must be re-applied after every merge; `grep` for the exact marker to detect silent drops.
> - **Overlay** — deep modifications of upstream code. Each entry has an inline reason — review the file and its upstream equivalent on every merge.

**Last regenerated against:** `upstream/v0.9.2` (commit `8dae237a0`) — replace on next merge.

---

## 1. Additive — new backend modules

| Path | Purpose |
|---|---|
| `backend/open_webui/routers/processing.py` | Admin dashboard for document-processing tasks. Registered in `main.py` (see Injection below). |
| `backend/open_webui/models/processing.py` | `ProcessingTask` ORM + `ProcessingTasks` repository + enums. |
| `backend/open_webui/utils/graph_client.py` | Microsoft Graph client used by SharePoint import + OAuth tools. |
| `backend/open_webui/retrieval/models.py` | RAG settings models (per-level, per-query overrides). |
| `backend/open_webui/migrations/_fork_helpers.py` | `create_table_if_missing`, `add_column_if_missing`, `drop_table_if_exists`, `drop_column_if_exists`. Used by all fork-local migrations. |
| `backend/open_webui/migrations/versions/a8f52d3c1e7b_add_processing_task_table.py` | Creates `processing_task`. |
| `backend/open_webui/migrations/versions/c7d8e9f0a1b2_repair_custom_schema.py` | 2026-03 repair migration (idempotent re-creation of fork tables). **Do not port this pattern to new migrations** — see Alembic playbook. |
| `backend/open_webui/migrations/versions/d8e9f0a1b2c3_normalize_processing_task_metadata.py` | Renames `task_metadata` → `metadata` back. |
| `backend/open_webui/migrations/versions/f0a1b2c3d4e5_backfill_v09_tables_if_missing.py` | Strategy-A backfill for calendar / automation / shared_chat tables. |
| `backend/open_webui/migrations/versions/f1b2c3d4e5f6_backfill_v09_columns_if_missing.py` | Strategy-A backfill for chat.tasks/summary/last_read_at, note.is_pinned. |
| `backend/open_webui/migrations/versions/a2b3c4d5e6f7_backfill_processing_task_metadata_if_missing.py` | 2026-04-24 backfill for Stolley drift. |
| `backend/open_webui/migrations/versions/f1e2d3c4b5a6_add_access_grant_table.py` | Access-grant resource sharing (fork-local, but file was modified post-initial; audit at next merge to confirm it has not been rewritten in place). |

---

## 2. Additive — new frontend modules

| Path | Purpose |
|---|---|
| `src/lib/apis/admin/processing.ts` | Client for `/api/v1/admin/processing`. |
| `src/lib/stores/processing.ts` | Svelte store + polling logic for the processing dashboard. |
| `src/lib/components/admin/Processing.svelte` | The dashboard UI. |
| `src/routes/(app)/admin/processing/+page.svelte` | Route wrapper. |
| `src/lib/components/workspace/Knowledge/SharePointPicker.svelte` | SharePoint site/library/folder browser for knowledge import. |
| `src/lib/components/common/RagSettingsModal.svelte` | Per-knowledge-base RAG settings modal. |
| `src/lib/utils/onedrive-file-picker.test.ts` | Unit tests for the OneDrive picker (upstream ships none). |

---

## 3. Additive — tests

| Path | Purpose |
|---|---|
| `backend/open_webui/test/processing/test_processing_models.py` | 42 model-level tests. |
| `backend/open_webui/test/processing/test_processing_api.py` | 19 API-level tests (note: currently errors at collection in some environments due to Base.metadata double-registration; see file-based variant below). |
| `backend/open_webui/test/processing/test_processing_router_registration.py` | Regression tests for router registration + retry handler shape. File-based, no heavy imports. |
| `backend/open_webui/test/retrieval/test_bm25_keyword_integration.py` | BM25 integration. |
| `backend/open_webui/test/retrieval/test_bm25_tokenization.py` | BM25 tokenization. |
| `backend/open_webui/test/retrieval/test_hybrid_search_deep_dive.py` | Hybrid search semantics. |
| `backend/open_webui/test/retrieval/test_keyword_matching.py` | Keyword-match scoring. |
| `backend/open_webui/test/retrieval/test_rag_models.py` | RAG settings Pydantic models. |
| `backend/open_webui/test/retrieval/test_rag_query_settings.py` | Per-query overrides. |
| `backend/open_webui/test/retrieval/test_rag_settings.py` | Global RAG settings. |
| `backend/open_webui/test/sharepoint/test_graph_client.py` | Graph client unit tests. |
| `backend/open_webui/test/sharepoint/test_sharepoint_import.py` | SharePoint import end-to-end. |

---

## 4. Additive — docs, PRPs, research

Large tree of planning / research documents. Zero conflict risk. Files:

- `docs/ALEMBIC_MERGE_PLAYBOOK.md`, `docs/CHANNELS_RAG_LIMITATIONS.md`, `docs/OAUTH_TOKEN_TOOL_FLOW.md`, `docs/ONBOARDING_BASICS_DE.md`, `docs/QUERY_GENERATION_PROMPT_ANALYSIS.md`, `docs/FORK_CHANGES.md` (this file)
- `backend/open_webui/docs/TEMPLATE_VARIABLES.md`, `backend/open_webui/docs/deep-linking.md`, `backend/open_webui/docs/external-loader-api.md`
- `PRPs/` — entire tree (requirements, plans, exploration templates, workshops)
- Root-level: `MICROSOFT_ENTRA_ID_OAUTH_SETUP.md`, `MICROSOFT_OAUTH_QUICKSTART.md`, `OAUTH_RESEARCH_INDEX.md`, `OPEN_WEBUI_K8S_PRODUCTION_RESEARCH.md`, `RAG_*.md`, `WORKSHOP_PRESENTATION_OUTLINE.md`

---

## 5. Additive — CI, tooling, infra

| Path | Purpose |
|---|---|
| `.github/workflows/azure-acr-build.yaml` | Our ACR build on push to `main` / `feature/**`. |
| `.github/workflows/build-release.yml.disabled` | Upstream release workflow, disabled by rename. |
| `.github/workflows/docker-build.yaml.disabled` | Same. |
| `.github/workflows/format-backend.yaml.disabled` | Same. |
| `.github/workflows/format-build-frontend.yaml.disabled` | Same. |
| `.github/workflows/release-pypi.yml.disabled` | Same. |
| `.github/workflows/codespell.disabled`, `integration-test.disabled`, `lint-*.disabled` | Same. |
| `.mcp.json` | Claude Code MCP server config. |
| `backend/start-dev.bat` | Local Windows dev launcher. |
| `migration_scripts/` | SQLite → Postgres migration + config-dump helpers. |
| `migrate-openwebui.load` | pgloader config. |
| `.gitignore` additions | Fork-local ignores. |

---

## 6. Injection — upstream hotspots with small fork hooks

> Re-apply after every merge. Grep markers are given for detection.

### `backend/open_webui/main.py`

- **Import block** — add `processing,` to the `from open_webui.routers import (...)` list.
  Detector: `grep -n "^    processing,$" backend/open_webui/main.py`
- **Router registration** — add under the retrieval router include:
  ```python
  app.include_router(processing.router, prefix='/api/v1/admin/processing', tags=['processing'])
  ```
  Detector: `grep -n "processing.router" backend/open_webui/main.py`

### `backend/open_webui/config.py`

- New `PersistentConfig` fields for fork features (~47 lines diff vs upstream). Categories to re-apply:
  - Processing dashboard config (if any),
  - RAG enhancements,
  - SharePoint / Graph API credentials,
  - Pseudonymizer feature flags.
  Detector: `git diff upstream/main..HEAD -- backend/open_webui/config.py` at next merge.

### `backend/open_webui/env.py`

- 15 lines of new env-var reads (Graph client, SharePoint, dev toggles).
  Detector: `grep -nE "GRAPH_|SHAREPOINT_|PSEUDONYMIZER" backend/open_webui/env.py`

### `backend/open_webui/internal/db.py`

- ~105 lines of fork additions. Includes:
  - `validate_all_schemas` / `SchemaValidationError` (Stolley-style startup validation),
  - `get_async_db_context` helper,
  - `JSONField` type wrapper.
  Detector: `grep -nE "validate_all_schemas|SchemaValidationError|get_async_db_context" backend/open_webui/internal/db.py`

### `backend/open_webui/routers/retrieval.py`

- 38 lines of hook points around `process_file` to feed the processing dashboard + pseudonymizer.
  Detector: `grep -nE "ProcessingTaskTracker|pseudonymizer" backend/open_webui/routers/retrieval.py`

### `backend/open_webui/utils/task.py`

- 19 lines of additions.
  Detector: `git diff upstream/main..HEAD -- backend/open_webui/utils/task.py` at next merge.

### `backend/open_webui/retrieval/vector/dbs/chroma.py`

- 4-line fork diff.
  Detector: `git diff upstream/main..HEAD -- backend/open_webui/retrieval/vector/dbs/chroma.py`

### `backend/open_webui/utils/tools.py`

- `clean_openai_tool_schema` injects empty `properties: {}` for parameter-less object schemas
  before downstream cleaning. Required because MCP servers (Dropbox, others) emit
  `{"type":"object"}` for tools without args, which OpenAI strict-mode function calling rejects
  with `"Invalid schema for function 'X': In context=(), object schema missing properties"`.
  Detector: `grep -n "OpenAI strict-mode rejects object schemas" backend/open_webui/utils/tools.py`

### `backend/open_webui/utils/mcp/client.py`

- `list_tool_specs` injects empty `properties: {}` into `inputSchema` for parameter-less
  MCP tools. The MCP code path bypasses `clean_openai_tool_schema` entirely
  (middleware.py packs `tool_spec` directly into `mcp_tools_dict`), so the fix has to
  live at the MCP-client boundary as well.
  Detector: `grep -n "OpenAI strict-mode rejects object schemas" backend/open_webui/utils/mcp/client.py`

### `backend/requirements.txt`

- 2-line diff (probably `ddgs` pin per commit `9776af725`).
  Detector: `diff`.

### Frontend injections

- `src/routes/(app)/admin/+layout.svelte` — 8 lines: add `/admin/processing` to admin nav.
- `src/lib/components/common/FileItem.svelte` — 4 lines.
- `src/lib/components/chat/MessageInput.svelte` — 18 lines.
- `src/lib/components/workspace/Knowledge/KnowledgeBase/AddContentMenu.svelte` — 23 lines: SharePoint picker entry.
- `src/lib/apis/knowledge/index.ts` — 286 lines (borderline overlay; audit at merge).

---

## 7. Overlay — deep fork modifications of upstream files

> Every upstream touch of these files re-conflicts. Review inline "why" comments before resolving. Consider decomposing into Additive + Injection at the next major refactor.

| Path | Fork diff | Reason |
|---|---|---|
| `backend/open_webui/retrieval/utils.py` | **2008 lines** (hotspot, 99.4th percentile churn) | RAG enhancements: BM25, hybrid search, per-level settings, citation improvements. Highest merge-risk file in the fork. |
| `backend/open_webui/routers/knowledge.py` | **649 lines** | Knowledge-base ACL + SharePoint import + RAG settings endpoints. |
| `backend/open_webui/utils/middleware.py` | 166 lines (hotspot, 99.7th percentile) | Pseudonymizer hooks, fork-local logging, possibly auth header extensions. |
| `backend/open_webui/models/knowledge.py` | 58 lines | KB shape additions for ACL / SharePoint source tracking. |
| `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` | 302 lines | SharePoint import UI, per-KB RAG settings UI. |
| `src/lib/components/admin/Settings/Documents.svelte` | 85 lines | Admin document-processing settings. |
| `src/lib/utils/onedrive-file-picker.ts` | 113 lines | Graph API adjustments. |
| `src/lib/components/chat/Messages/Citations/CitationModal.svelte` | 64 lines | Extended citation metadata display. |
| `src/lib/components/chat/Settings/General.svelte` | 50 lines | User-level settings extensions. |
| `src/lib/components/workspace/Models/ModelEditor.svelte` | 69 lines | Model editor additions. |

---

## 8. Binary / static overlays (ignore on merge unless intentional)

- `backend/open_webui/static/favicon.ico`, `favicon.png` — fork-branded favicons.
- `static/pyodide/pyodide-lock.json` — regenerated by build; do not hand-resolve, prefer `--theirs` then rebuild.

---

## 9. Customer branches currently in flight

| Customer | Branch | Image tag | Notes |
|---|---|---|---|
| Stolley | `feature/sharepoint-kb-integration` | `git-7ed08b4` (post 2026-04-24 processing-router fix) | Cut `release/stolley-2026-04-24` before next merge. |
| Stadtbau | `main` (at prior main-HEAD) | see `nashtrader/stadtbau-k8s` | Cut `release/stadtbau-<date>` before next merge. |
| PV | `customer` remote on net-solution-GmbH | — | Push target: `customer`, not `origin`. See `brain/references/pv-openwebui-deploy.md`. |

---

## 10. Regeneration recipe

After every upstream merge, before commit:

```bash
git fetch upstream
git diff upstream/<new-tag>..HEAD --stat > /tmp/fork-stat.txt
# Walk /tmp/fork-stat.txt; update line counts and categorize any newly-changed file.
# Files that appear for the first time → Additive by default.
# Files with > 30 line diff against upstream → consider promoting to Overlay.
```

The alembic-merge skill refuses to complete a merge PR without this file being updated in the same commit.
