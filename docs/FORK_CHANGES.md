# FORK_CHANGES.md

> **Inventory of every fork-local deviation from upstream.** Regenerate this file after every upstream merge — line numbers drift otherwise. See `.claude/skills/alembic-merge/SKILL.md` Step 8 for regeneration, and the `alembic-merge` skill for the re-apply workflow during conflict resolution.
>
> Categories:
> - **Additive** — new modules / new directories. Zero conflict risk with upstream.
> - **Injection** — 2–10 line hooks into upstream hotspots. Must be re-applied after every merge; `grep` for the exact marker to detect silent drops.
> - **Overlay** — deep modifications of upstream code. Each entry has an inline reason — review the file and its upstream equivalent on every merge.
>
> **Detector convention:** all detectors diff against the merged upstream tag (`git diff v0.11.0..HEAD -- <file>`), NOT `upstream/main` — diffing against a moving ref produced false "clean" results twice (chroma fix, ddgs pin; see 0.10.2 triage §4.3).

**Last regenerated against:** `v0.11.0` (merge on `feature/owui-0.11.0`, 2026-07-27).

> **UI note (0.11.0):** upstream rebuilt the entire interface. Admin settings moved to an
> `AdminSettingSection` / `AdminSettingRow` / `AdminSettingField` component idiom, user settings
> to `UserSetting*`, and the inline Access button became `<AccessButton />`. All fork settings
> markup was reshaped into those components — a fork block written in the old raw-`<div>` style
> will look wrong and must be ported, not pasted.

> **Config-system note (0.10.2, still current in 0.11.0):** upstream replaced the entire
> `ConfigVar`/`AppConfig` layer with a per-key DB model: `open_webui/models/config.py`,
> table `config` (`key`, `value`, `updated_at`), read via `await Config.get('dotted.key')` /
> `Config.get_many(...)`, defaults seeded from the `DEFAULT_CONFIG` dict in `config.py`.
> All fork configs are registered there.

---

## 1. Additive — new backend modules

| Path | Purpose |
|---|---|
| `backend/open_webui/routers/processing.py` | Admin dashboard for document-processing tasks. Registered in `main.py` (see Injection below). |
| `backend/open_webui/models/processing.py` | `ProcessingTask` ORM + `ProcessingTasks` repository + `ProcessingTaskTracker` + enums. |
| `backend/open_webui/utils/graph_client.py` | Microsoft Graph client used by SharePoint import + OAuth tools. |
| `backend/open_webui/retrieval/models.py` | RAG settings models (per-level, per-query overrides). Still absent upstream in v0.11.0. |
| `backend/open_webui/migrations/_fork_helpers.py` | `create_table_if_missing`, `add_column_if_missing`, `drop_table_if_exists`, `drop_column_if_exists`. Used by all fork-local migrations. |
| `backend/open_webui/migrations/versions/a8f52d3c1e7b_add_processing_task_table.py` | Creates `processing_task`. |
| `backend/open_webui/migrations/versions/c7d8e9f0a1b2_repair_custom_schema.py` | 2026-03 repair migration. **Do not port this pattern to new migrations** — see Alembic playbook. |
| `backend/open_webui/migrations/versions/d8e9f0a1b2c3_normalize_processing_task_metadata.py` | Renames `task_metadata` → `metadata` back. |
| `backend/open_webui/migrations/versions/f0a1b2c3d4e5_backfill_v09_tables_if_missing.py` | Strategy-A backfill for calendar / automation / shared_chat tables. |
| `backend/open_webui/migrations/versions/f1b2c3d4e5f6_backfill_v09_columns_if_missing.py` | Strategy-A backfill for chat.tasks/summary/last_read_at, note.is_pinned. |
| `backend/open_webui/migrations/versions/a2b3c4d5e6f7_backfill_processing_task_metadata_if_missing.py` | 2026-04-24 backfill for Stolley drift. |
| `backend/open_webui/migrations/versions/f1e2d3c4b5a6_add_access_grant_table.py` | Same-node body conflict vs upstream (idempotent fork `upgrade()` body kept); AccessGrants ACL itself is upstream-legacy — see 0.9.6 triage §4.7. |
| `backend/open_webui/migrations/versions/7e66bdd43a43_merge_upstream_v0_9_6_fork_recovery_.py` | Alembic merge node (0.9.6 replay recovery). No DDL. |
| `backend/open_webui/migrations/versions/e48721182479_merge_upstream_v0_10_2.py` | Alembic merge node for v0.10.2 (`42e2978c7933` + `7e66bdd43a43`). No DDL. |
| `backend/open_webui/migrations/versions/ad192b50687b_merge_upstream_v0_11_0.py` | Alembic merge node for v0.11.0 (`e48721182479` + `f0bd01a18a3d`). No DDL. |

## 2. Additive — new frontend modules

| Path | Purpose |
|---|---|
| `src/lib/apis/admin/processing.ts` | Client for `/api/v1/admin/processing`. |
| `src/lib/stores/processing.ts` | Svelte store + polling logic for the processing dashboard. |
| `src/lib/components/admin/Processing.svelte` | The dashboard UI. |
| `src/routes/(app)/admin/processing/+page.svelte` | Route wrapper. |
| `src/lib/components/workspace/Knowledge/SharePointPicker.svelte` | SharePoint site/library/folder browser for knowledge import. |
| `src/lib/components/common/RagSettingsModal.svelte` | Per-knowledge-base / per-model / per-user RAG settings modal. |
| `src/lib/utils/onedrive-file-picker.test.ts` | Unit tests for the OneDrive picker (upstream ships none). **Currently red — see §11.** |

## 3. Additive — tests

All under `backend/open_webui/test/`: `processing/` (models, api, router registration), `retrieval/` (bm25 tokenization + keyword integration, hybrid deep dive, keyword matching, rag models/settings/query settings, native-FC force retrieval, embedding function signature), `sharepoint/` (graph client, sharepoint import). Full fork suite: **321 tests, green on the v0.11.0 merge** (unchanged count vs 0.10.2).

Run them with `joserfc` installed — it became a hard backend dependency (`requirements.txt`) and `utils/oauth.py` imports it at module load, so the sharepoint suite fails at *collection* without it.

## 4. Additive — docs, PRPs, research

- `docs/` fork docs incl. this file, `ALEMBIC_MERGE_PLAYBOOK.md`, `UPSTREAM_0.9.6_TRIAGE.md`, `UPSTREAM_0.10.2_TRIAGE.md`, `UPSTREAM_0.11.0_TRIAGE.md`, `OWUI_0.9.6_REPLAY_REPORT.md`, OAuth/RAG analyses, `deploy-test/` tooling; `backend/open_webui/docs/*`; `PRPs/` tree; root-level research MDs (`RAG_*`, `MICROSOFT_*`, `OAUTH_*`, K8s research).

## 5. Additive — CI, tooling, infra

`.github/workflows/azure-acr-build.yaml` is the **only active workflow**; the upstream workflow set is disabled by `.disabled` rename — re-apply the rename on every upstream bump. **v0.11.0 added `issue-label.yaml`; it has been renamed to `.disabled`.** Check for new upstream workflows on every merge:

```bash
ls .github/workflows/ | grep -v '\.disabled$'   # must print only azure-acr-build.yaml
```

Plus `.mcp.json`, `backend/start-dev.bat`, `migration_scripts/`, `migrate-openwebui.load`, `.gitignore` additions.

---

## 6. Injection — upstream hotspots with small fork hooks

### `backend/open_webui/main.py`

- Import `processing,` in the routers import list. Detector: `grep -n "^    processing,$" backend/open_webui/main.py`
- `app.include_router(processing.router, prefix='/api/v1/admin/processing', tags=['processing'])`. Detector: `grep -n "processing.router" backend/open_webui/main.py`
- `/api/config`: `'client_id_business': config.get('onedrive.client_id_business') or ONEDRIVE_CLIENT_ID_BUSINESS` + key in the surrounding `Config.get_many` list. Detector: `grep -n "onedrive.client_id_business" backend/open_webui/main.py`

### `backend/open_webui/config.py`

Per-key registrations (module-level env default + `DEFAULT_CONFIG` entry each), all marked `# FORK:`:

- `RAG_NATIVE_FC_FORCE_RETRIEVAL` → `'rag.native_fc_force_retrieval'` (default `True`)
- `ENABLE_RAG_RERANKING` → `'rag.enable_reranking'` (default `True`) — upstream has `rag.reranking_engine/model/batch_size` but still no on/off gate
- `SHAREPOINT_IMPORT_MAX_TOTAL_SIZE_MB` → `'rag.sharepoint.import_max_total_size_mb'` (default `200`)
- `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE` → `'code_interpreter.pyodide_prompt_template'` (default `''`)
- `'onedrive.client_id_business'` → `ONEDRIVE_CLIENT_ID_BUSINESS` (upstream keeps it env-only)
- `DEFAULT_RAG_TEMPLATE` **overlay**: fork template with `{{KNOWLEDGE_BASES}}`, `{{QUERY}}`, strict `[id]`-citation rules (pairs with the `utils/task.py` injection).

Detector: `grep -n "# FORK:" backend/open_webui/config.py` (expect 4) and `grep -n "KNOWLEDGE_BASES" backend/open_webui/config.py`

### `backend/open_webui/routers/configs.py`

- `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE` in `CODE_EXECUTION_CONFIG_KEYS` map + `CodeInterpreterConfigForm` field (GET/POST run generically off the map). Detector: `grep -n "PYODIDE_PROMPT_TEMPLATE" backend/open_webui/routers/configs.py` (expect 2 hits)

### `backend/open_webui/routers/retrieval.py`

- `RAG_NATIVE_FC_FORCE_RETRIEVAL` + `ENABLE_RAG_RERANKING` in `RETRIEVAL_CONFIG_KEYS`. Detector: `grep -n "native_fc_force_retrieval\|enable_reranking" backend/open_webui/routers/retrieval.py`
- **ProcessingTaskTracker hooks (restored 2026-07-27):** `_safe_track`, `_start_processing_tracker`, and the `process_file` route / `_process_file(tracker=...)` split. Detector: `grep -n "_start_processing_tracker\|async def _process_file" backend/open_webui/routers/retrieval.py`

### `backend/open_webui/routers/files.py`

- Upload pipeline imports `_process_file` / `_start_processing_tracker` / `_safe_track` and threads one tracker through all three call sites (one upload = one dashboard row). Detector: `grep -n "_start_processing_tracker" backend/open_webui/routers/files.py`

### `backend/open_webui/routers/processing.py`

- Retry reuses the existing task via `ProcessingTaskTracker(task_id, db=new_db)` instead of letting `_process_file` create a second row. Detector: `grep -n "tracker = ProcessingTaskTracker" backend/open_webui/routers/processing.py`

### `backend/open_webui/env.py`

- `FORK_VERSION_SUFFIX`, 4× `EMBEDDING_RETRY_*`, `GRAPH_*` / SharePoint / dev toggles. Name-disjoint from upstream. Detector: `grep -nE "FORK_VERSION_SUFFIX|EMBEDDING_RETRY_|GRAPH_|SHAREPOINT_" backend/open_webui/env.py`

### `backend/open_webui/internal/db.py`

- `JSONField.process_result_value` native-JSON passthrough (`if isinstance(value, (dict, list)): return value`). Upstream is still a bare `json.loads`. Detector: `grep -n "isinstance(value, (dict, list))" backend/open_webui/internal/db.py`
- Startup schema-validation block stays **deleted** (0.9.6 decision) — do not re-apply.

### `backend/open_webui/utils/tools.py` / `backend/open_webui/utils/mcp/client.py`

- Empty `properties: {}` injection for parameter-less object schemas (OpenAI strict mode). Upstream's `clean_properties` (v0.11.0) still does not do this. Detector: `grep -n "OpenAI strict-mode rejects object schemas" backend/open_webui/utils/tools.py backend/open_webui/utils/mcp/client.py`

### `backend/open_webui/utils/task.py`

- `rag_template()` accepts `knowledge_bases` + renders `{{KNOWLEDGE_BASES}}`. Upstream signature is `async def rag_template(template, context, query)`; the fork appends a defaulted 4th parameter. Detector: `grep -n "KNOWLEDGE_BASES" backend/open_webui/utils/task.py`
- **Known gap:** no caller passes `knowledge_bases`, so `{{KNOWLEDGE_BASES}}` renders empty. Pre-existing since 0.10.2, not a merge regression — see §11.

### Frontend injections

- `src/routes/(app)/admin/+layout.svelte` — `/admin/processing` nav entry (uses the 0.11.0 `px-1 text-sm` tab class).
- `src/lib/components/common/FileItem.svelte` — 4 lines.
- `src/lib/components/workspace/Knowledge/KnowledgeBase/Files.svelte` — `onEdit` prop + "Edit content" menu entry (11 lines).
- `src/lib/components/workspace/Knowledge/KnowledgeBase/AddContentMenu.svelte` — SharePoint picker entry (46 lines).
- `src/lib/components/admin/Settings/Documents.svelte` — force-retrieval `AdminSettingRow` at the top of the Retrieval section (14 lines).
- `src/lib/components/admin/Settings/CodeExecution.svelte` — pyodide prompt `AdminSettingField` in the Code Interpreter section (17 lines).
- `src/lib/components/chat/MessageInput.svelte` + `src/lib/components/chat/Settings/Interface.svelte` — **shrunk in 0.11.0.** Upstream now ships a `defaultUploadContext` user setting (`'full' | 'focused'`, upstream default `'focused'`); the fork only flips the unset default to `'full'` in both files. The former ~21-line unconditional override is gone. Detector: `grep -n "FORK" src/lib/components/chat/Settings/Interface.svelte`
- `src/lib/i18n/locales/{de-DE,en-US}/translation.json` — force-retrieval label/tooltip keys.

---

## 7. Overlay — deep fork modifications of upstream files

| Path | Fork diff vs v0.11.0 | Reason |
|---|---|---|
| `backend/open_webui/routers/knowledge.py` | +931 / −1 | SharePoint import block (`/{id}/sharepoint/*`, `/sharepoint/sites*`) + `/{id}/reindex`; write access guarded by upstream `is_external_knowledge`; size limit via `Config.get('rag.sharepoint.import_max_total_size_mb')`. Per-KB rag_settings ride the standard `meta` update endpoint (no separate route). Merged cleanly into 0.11.0. |
| `backend/open_webui/retrieval/utils.py` | +880 / −149 | RAG enhancements: `tokenize_for_bm25`, `ScoringBM25Retriever` (upstream still calls bare `BM25Retriever.from_texts`), `extract_matched_keywords` citations, embedding retry framework, `enable_reranking` gate, `filter_results_by_relevance`, `merge_rag_settings`, `*_with_settings` wrappers, per-KB override resolution in `get_sources_from_items`. **Upstream's native pgvector hybrid path and the external-KB branch stay untouched** — fork logic only extends the local-collection fallback. |
| `src/lib/apis/knowledge/index.ts` | +411 / −0 | SharePoint + reindex + per-KB API client functions. |
| `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` | +398 / −4 | SharePoint import UI, per-KB RAG settings, reindex, preview split — all gated off for external KBs (`meta.source === 'external'`). Header buttons reshaped around 0.11.0's `<AccessButton />`. Also the upload-spinner cleanup in `uploadFileHandler` (upstream fixed only the directory-upload handler). |
| `backend/open_webui/utils/middleware.py` | +107 / −24 | **KB-deterministic-inject** (`# FORK: KB-deterministic-inject`): force-retrieval gate on both injection sites; the `folder_knowledge` sidecar now uses upstream's `get_owner_accessible_folder_files(folder)` (v0.11.0 security fix — filter against the folder OWNER, not the caller). **Per-level RAG settings** (`# FORK: per-level RAG settings`): global < user < model cascade + per-KB overrides, batched through one `Config.get_many` that is a superset of upstream's. **Blank-query full-context fallback.** **Pyodide prompt override** feeding both append sites via one variable. Detector: `grep -n "# FORK:" backend/open_webui/utils/middleware.py` (expect 7: 1 blank-query, 2 per-level RAG, 3 KB-deterministic-inject, 1 pyodide) |
| `src/lib/utils/onedrive-file-picker.ts` | +103 / −10 | Graph API adjustments. |
| `backend/open_webui/routers/retrieval.py` | +97 / −1 | Fork config keys + the ProcessingTaskTracker split (see §6). |
| `src/lib/components/chat/Messages/Citations/CitationModal.svelte` | +73 / −0 | Extended citation metadata display (matched keywords). |
| `src/lib/components/workspace/Models/ModelEditor.svelte` | +58 / −0 | Per-model RAG settings section (`info.meta.rag_settings`), reshaped into the 0.11.0 layout. |
| `src/lib/components/chat/Settings/General.svelte` | +54 / −0 | User-level RAG settings (`$settings.rag_settings`). |
| `backend/open_webui/models/knowledge.py` | +38 / −15 | `RagSettings` + `KnowledgeMeta` models, `meta` on `KnowledgeForm`, `update_knowledge_meta_by_id`. |
| `backend/open_webui/routers/files.py` | +23 / −4 | Tracker wiring (see §6). |

**Resolved by v0.11.0 (removed from this inventory):**
- Chat-upload full-context override — upstream shipped the `defaultUploadContext` setting (#20900); the fork entry shrank to a default flip (§6).
- KnowledgeBase directory-upload spinner leak — upstream fixed that handler; only `uploadFileHandler` remains fork-patched.

**Resolved earlier by v0.10.2:** Chroma `has_collection` fix (upstream `15d96b1f2`, further optimized in 0.11.0 by #27394), `ddgs` requirements pin, `folder_knowledge` sidecar consumption (upstream-native in `utils/tools.py`).

## 8. Binary / static overlays

- `backend/open_webui/static/favicon.ico`, `favicon.png` — fork favicons, **but see §11: they are inert.** `config.py` deletes every loose file in `STATIC_DIR` at import and repopulates from the frontend build, so these are overwritten on every startup. Real branding belongs in the frontend `static/` tree.
- `static/pyodide/pyodide-lock.json` — regenerated by build; prefer `--theirs` then rebuild.

## 9. Customer branches currently in flight

| Customer | Branch | Notes |
|---|---|---|
| Stolley | `feature/sharepoint-kb-integration` | `release/stolley-2026-04-24` already cut. |
| Stadtbau | `main` (at prior main-HEAD) | Cut `release/stadtbau-<date>` before merging `feature/owui-0.11.0` to `main`. |
| Falkensteg | AKS `aks-falkensteg`, pgvector | See `docs/deploy-test/instances.json`. Cut a release branch before the merge to `main`. |
| PV | `customer` remote on net-solution-GmbH | Push target: `customer`, not `origin`. |

**No customer branch tracks `feature/owui-0.11.0`** — the merge landed on a feature branch, so nothing was dragged along. Release cuts are owed before this reaches `main`.

## 10. Regeneration recipe

```bash
git diff v0.11.0..HEAD --stat            # walk, update counts, categorize new files
grep -rn "# FORK:" backend/open_webui/config.py backend/open_webui/utils/middleware.py
ls .github/workflows/ | grep -v '\.disabled$'   # only azure-acr-build.yaml
```

The alembic-merge skill refuses to complete a merge PR without this file being updated in the same commit.

## 11. Standing defects (not merge regressions)

Verified pre-existing on `feature/owui-0.10.2`; carried forward untouched.

1. **`backend/open_webui/static/` is wiped by any backend import.** `config.py` (unchanged since ≤ v0.10.2) unlinks every loose file in `STATIC_DIR`, then repopulates from `FRONTEND_BUILD_DIR/static`. In a dev checkout with no frontend build, the directory is left stripped — so `pytest`, `alembic`, or a bare backend start silently delete tracked assets, and a later `git add -A` commits the deletion. **This already happened once:** the 2026-07-15 emergency WIP commit recorded favicons byte-identical to upstream, i.e. the fork branding had been overwritten from a build output, not updated. Always check `git status backend/open_webui/static/` before staging after running backend tooling.
2. **`{{KNOWLEDGE_BASES}}` is never populated.** `rag_template()` accepts `knowledge_bases`, but no caller passes it (`middleware.py` has three call sites, all 3-arg). The template variable renders empty.
3. **`src/lib/utils/onedrive-file-picker.test.ts` is red (9 of 13 tests).** Every failure is `window is not defined`: the repo declares no `jsdom`/`happy-dom` dependency and `vite.config.ts` sets no test environment. Test file, module under test, vitest (1.6.1), `@azure/msal-browser` (4.5.0) and `vite.config.ts` are byte-identical to the 0.10.2 branch, so this is unrelated to the v0.11.0 merge.
4. **Fork type extensions are untyped.** `info.meta.rag_settings`, `Settings.rag_settings` and `config.enable_onedrive_business` produce `svelte-check` errors because no fork type declarations exist. Baseline: `npm run check` reports 8465 errors on the fork vs 8433 with the eight conflicted files reverted to upstream — the +32 are these untyped properties plus proportionally more implicit-`any` noise in the larger fork files, no new error class.
