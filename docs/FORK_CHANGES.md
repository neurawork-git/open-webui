# FORK_CHANGES.md

> **Inventory of every fork-local deviation from upstream.** Regenerate this file after every upstream merge — line numbers drift otherwise. See `.claude/skills/alembic-merge/SKILL.md` Step 8 for regeneration, and the `alembic-merge` skill for the re-apply workflow during conflict resolution.
>
> Categories:
> - **Additive** — new modules / new directories. Zero conflict risk with upstream.
> - **Injection** — 2–10 line hooks into upstream hotspots. Must be re-applied after every merge; `grep` for the exact marker to detect silent drops.
> - **Overlay** — deep modifications of upstream code. Each entry has an inline reason — review the file and its upstream equivalent on every merge.
>
> **Detector convention:** all detectors diff against the merged upstream tag (`git diff v0.10.2..HEAD -- <file>`), NOT `upstream/main` — diffing against a moving ref produced false "clean" results twice (chroma fix, ddgs pin; see 0.10.2 triage §4.3).

**Last regenerated against:** `v0.10.2` (merge on `feature/owui-0.10.2`, 2026-07-14).

> **Config-system note (0.10.2):** upstream replaced the entire `ConfigVar`/`AppConfig` layer
> (which v0.9.6 had itself introduced) with a per-key DB model:
> `open_webui/models/config.py`, table `config` (`key`, `value`, `updated_at`), read via
> `await Config.get('dotted.key')` / `Config.get_many(...)`, defaults seeded from the
> `DEFAULT_CONFIG` dict in `config.py`. All fork configs are registered there; the reshape
> migration `3ff2c63645b8` copies unknown blob leaf paths as-is and preserves the old blob
> as `config_old`, so fork values survive the upgrade without a fork-side migration.

---

## 1. Additive — new backend modules

| Path | Purpose |
|---|---|
| `backend/open_webui/routers/processing.py` | Admin dashboard for document-processing tasks. Registered in `main.py` (see Injection below). |
| `backend/open_webui/models/processing.py` | `ProcessingTask` ORM + `ProcessingTasks` repository + enums. |
| `backend/open_webui/utils/graph_client.py` | Microsoft Graph client used by SharePoint import + OAuth tools. |
| `backend/open_webui/utils/sharepoint_backend.py` | `SharePointBackend` protocol + `get_sharepoint_backend()` resolver. Chooses Graph (OAuth) or on-prem (NTLM) per `SHAREPOINT_BACKEND`. The protocol is derived verbatim from `GraphClient`'s signatures, so `GraphClient` satisfies it with **no adapter** — the cloud path carries no new code. Also owns the credential write path (`maybe_store_ldap_credential`) and the delete-on-rejection rule. **The decrypted password never leaves this module.** |
| `backend/open_webui/utils/sharepoint_onprem_client.py` | SharePoint SE client over NTLM (`pyspnego` + a hand-written `httpx.Auth`). Uses the classic `_api/web` route for folders/files — the `/_api/v2.0/` dialect answers 400 as soon as a library is non-empty (measured 2026-07-31). |
| `backend/open_webui/models/user_credentials.py` | `UserCredential` ORM + `UserCredentialsTable`. AES-256-GCM (not Fernet) with `user_id` as AAD and a `key_id` per row. No API ever returns the secret. |
| `backend/open_webui/migrations/versions/e7f8a9b0c1d2_add_user_credential_table.py` | Creates `user_credential`. Downgrade drops it — rolling back must not leave secrets behind. |
| `backend/open_webui/retrieval/models.py` | RAG settings models (per-level, per-query overrides). `RAGQuerySettings.from_config` is async and reads `Config.get_many` (0.10.2 port). |
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

## 2. Additive — new frontend modules

| Path | Purpose |
|---|---|
| `src/lib/apis/admin/processing.ts` | Client for `/api/v1/admin/processing`. |
| `src/lib/stores/processing.ts` | Svelte store + polling logic for the processing dashboard. |
| `src/lib/components/admin/Processing.svelte` | The dashboard UI. |
| `src/routes/(app)/admin/processing/+page.svelte` | Route wrapper. |
| `src/lib/components/workspace/Knowledge/SharePointPicker.svelte` | SharePoint site/library/folder browser for knowledge import. |
| `src/lib/components/common/RagSettingsModal.svelte` | Per-knowledge-base RAG settings modal. |
| `src/lib/components/chat/Settings/Account/CredentialStore.svelte` | Self-service panel for the LDAP credential store: status, opt-out switch, delete. Storing is the default while the feature is on, so this is the only in-product way out. Rendered from `Settings/Account.svelte` behind `features.enable_ldap_credential_store`. |
| `src/lib/utils/onedrive-file-picker.test.ts` | Unit tests for the OneDrive picker (upstream ships none). Stubs `window` via `vi.stubGlobal` — vitest runs in the `node` environment here and the module reads `window.location.origin`. Without the stub all 9 real assertions fail on `window is not defined`; don't "fix" that by adding jsdom. |

## 3. Additive — tests

All under `backend/open_webui/test/`: `processing/` (models, api, router registration), `retrieval/` (bm25 tokenization + keyword integration, hybrid deep dive, keyword matching, rag models/settings/query settings, native-FC force retrieval, embedding function signature), `sharepoint/` (graph client, sharepoint import, on-prem NTLM client, backend compat — **110 tests**, green 2026-08-03). Full fork suite: **321 tests** (green on the 0.10.2 merge).

- `backend/open_webui/test/conftest.py` — `pytest_sessionfinish` disposes the async engine. Without it aiosqlite's **non-daemon** connection worker keeps the interpreter alive after a green run, so pytest reports success and then hangs forever in `threading._shutdown()`. Detector: `ls backend/open_webui/test/conftest.py`.
- Running the backend suite needs `WEBUI_SECRET_KEY` set — otherwise `env.py:714` raises `SystemExit` at import and every test in the file fails with an unrelated-looking error.

## 4. Additive — docs, PRPs, research

- `docs/` fork docs incl. this file, `ALEMBIC_MERGE_PLAYBOOK.md`, `UPSTREAM_0.9.6_TRIAGE.md`, `UPSTREAM_0.10.2_TRIAGE.md`, `OWUI_0.9.6_REPLAY_REPORT.md`, OAuth/RAG analyses; `backend/open_webui/docs/*`; `PRPs/` tree; root-level research MDs (`RAG_*`, `MICROSOFT_*`, `OAUTH_*`, K8s research).

## 5. Additive — CI, tooling, infra

Unchanged from 0.9.6 regeneration: `.github/workflows/azure-acr-build.yaml` is the **only active workflow**; the upstream workflow set is disabled by `.disabled` rename — re-apply the rename on every upstream bump (0.10.2: upstream workflow set unchanged vs 0.9.6, renames carried through the merge). Plus `.mcp.json`, `backend/start-dev.bat`, `migration_scripts/`, `migrate-openwebui.load`, `.gitignore` additions.

---

## 6. Injection — upstream hotspots with small fork hooks

### `backend/open_webui/main.py`

- Import `processing,` in the routers import list. Detector: `grep -n "^    processing,$" backend/open_webui/main.py`
- `app.include_router(processing.router, prefix='/api/v1/admin/processing', tags=['processing'])` after the knowledge router. Detector: `grep -n "processing.router" backend/open_webui/main.py`
- `/api/config`: `'client_id_business': config.get('onedrive.client_id_business') or ONEDRIVE_CLIENT_ID_BUSINESS` + key in the surrounding `Config.get_many` list. Detector: `grep -n "onedrive.client_id_business" backend/open_webui/main.py`
- `/api/config`: `'enable_sharepoint_import': SHAREPOINT_BACKEND.strip() != ''` in the authenticated `features` block, plus `SHAREPOINT_BACKEND` in the `from open_webui.env import (...)` list. Un-hides the SharePoint picker (`KnowledgeBase.svelte`), which was previously gated on `enable_onedrive_integration && enable_onedrive_business` — both need an Entra app id, so `SHAREPOINT_BACKEND=onprem` could never reach it. Must sit **outside** the `if config.get('onedrive.enable')` dict-spread, or it disappears whenever OneDrive is off. Detector: `grep -n "enable_sharepoint_import" backend/open_webui/main.py`. Pinned by `test/sharepoint/test_sharepoint_backend_compat.py::TestSharePointPickerStaysVisibleOnGraph`.

### `backend/open_webui/config.py`

Per-key registrations (module-level env default + `DEFAULT_CONFIG` entry each), all marked `# FORK:`:

- `RAG_NATIVE_FC_FORCE_RETRIEVAL` → `'rag.native_fc_force_retrieval'` (default `True`)
- `ENABLE_RAG_RERANKING` → `'rag.enable_reranking'` (default `True`)
- `SHAREPOINT_IMPORT_MAX_TOTAL_SIZE_MB` → `'rag.sharepoint.import_max_total_size_mb'` (default `200`)
- `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE` → `'code_interpreter.pyodide_prompt_template'` (default `''`)
- `'onedrive.client_id_business'` → `ONEDRIVE_CLIENT_ID_BUSINESS` (upstream keeps it env-only)
- `DEFAULT_RAG_TEMPLATE` **overlay**: fork template with `{{KNOWLEDGE_BASES}}`, `{{QUERY}}`, strict `[id]`-citation rules (pairs with the `utils/task.py` injection).

Detector: `grep -n "# FORK:" backend/open_webui/config.py` and `grep -n "KNOWLEDGE_BASES" backend/open_webui/config.py`

### `backend/open_webui/routers/configs.py`

- `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE` in `CODE_EXECUTION_CONFIG_KEYS` map + `CodeInterpreterConfigForm` field (GET/POST run generically off the map). Detector: `grep -n "pyodide_prompt_template" backend/open_webui/routers/configs.py`

### `backend/open_webui/routers/retrieval.py`

- `RAG_NATIVE_FC_FORCE_RETRIEVAL` + `ENABLE_RAG_RERANKING` in `RETRIEVAL_CONFIG_KEYS` + `ConfigForm` fields + update handler. Detector: `grep -n "native_fc_force_retrieval\|enable_reranking" backend/open_webui/routers/retrieval.py`
- **ProcessingTaskTracker hooks: NOT present.** They were lost in the 2026-06 v0.9.6 replay and are currently being rebuilt as uncommitted WIP in the main working tree (routers/retrieval.py, files.py, processing.py, middleware.py). Rebase that WIP onto `feature/owui-0.10.2` and update this entry when it lands.

### `backend/open_webui/env.py`

- `FORK_VERSION_SUFFIX`, 4× `EMBEDDING_RETRY_*`, `GRAPH_*` / SharePoint / dev toggles. Name-disjoint from upstream. Detector: `grep -nE "FORK_VERSION_SUFFIX|EMBEDDING_RETRY_|GRAPH_|SHAREPOINT_" backend/open_webui/env.py`
- `ENABLE_VERSION_UPDATE_CHECK` **default overlay**: upstream ships `'true'`, the fork ships `'false'`. The check polls upstream's release tags, which cannot be installed on a fork. Detector: `grep -n "ENABLE_VERSION_UPDATE_CHECK" backend/open_webui/env.py` — if the default reads `'true'`, an upstream merge overwrote it.
- LDAP credential store + backend selection: `ENABLE_LDAP_CREDENTIAL_STORE`, `LDAP_CREDENTIAL_ENCRYPTION_KEY` (**no fallback to `WEBUI_SECRET_KEY`, deliberately**), `LDAP_CREDENTIAL_TTL`, `LDAP_NETBIOS_DOMAIN`, `SHAREPOINT_BACKEND`, `SHAREPOINT_ONPREM_SITE_URL`, `SHAREPOINT_ONPREM_VERIFY_TLS`. Detector: `grep -nE "LDAP_CREDENTIAL|SHAREPOINT_BACKEND|SHAREPOINT_ONPREM" backend/open_webui/env.py`

### `backend/open_webui/routers/auths.py`

- **LDAP credential capture** (marker `# FORK: capture the AD credential`): one call to `maybe_store_ldap_credential(user, username_list[0], form_data.password, db=db)` in the success branch of `ldap_auth`, right after the user is resolved. Opt-in gated, feature-flagged, never raises.
- **This sits in a path upstream edits often.** On every version bump, check whether `ldap_auth` was restructured and whether the call still lands after the successful user bind and after `user` exists. Deliberately kept to a single line so a rebase conflict stays small. Detector: `grep -n "maybe_store_ldap_credential" backend/open_webui/routers/auths.py`
- Note `entry_username` may be a list — always pass `username_list[0]`, never the raw attribute.

### `backend/open_webui/routers/users.py`

- Three self-service credential endpoints: `GET/POST /user/credentials/status|opt-in`, `DELETE /user/credentials/ad`. Own account only; **no endpoint returns the secret, not even for an admin**. Detector: `grep -n "user/credentials" backend/open_webui/routers/users.py`

### `backend/open_webui/internal/db.py`

- `JSONField.process_result_value` native-JSON passthrough (`if isinstance(value, (dict, list)): return value`). Detector: `grep -n "isinstance(value, (dict, list))" backend/open_webui/internal/db.py`
- Startup schema-validation block stays **deleted** (0.9.6 decision) — do not re-apply.

### `backend/open_webui/utils/tools.py` / `backend/open_webui/utils/mcp/client.py`

- Empty `properties: {}` injection for parameter-less object schemas (OpenAI strict mode). Detector: `grep -n "OpenAI strict-mode rejects object schemas" backend/open_webui/utils/tools.py backend/open_webui/utils/mcp/client.py`

### `backend/open_webui/utils/task.py`

- `rag_template()` accepts `knowledge_bases` + renders `{{KNOWLEDGE_BASES}}`. Detector: `grep -n "KNOWLEDGE_BASES" backend/open_webui/utils/task.py`

### `package.json`

- `"test:frontend": "vitest run --passWithNoTests"` — upstream omits `run`, so the script starts vitest in **watch mode** and never exits, which hangs any CI step or agent that calls it. Detector: `grep -n '"test:frontend"' package.json` — if `run` is gone, an upstream merge took it.

### Frontend injections

- `src/routes/(app)/admin/+layout.svelte` — `/admin/processing` nav entry.
- `src/lib/components/common/FileItem.svelte` — 4 lines.
- `src/lib/components/chat/MessageInput.svelte` — ~21 lines.
- `src/lib/components/workspace/Knowledge/KnowledgeBase/AddContentMenu.svelte` — SharePoint picker entry (46 lines).
- `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` — `showSharePointImport={!isExternalKnowledge && $config?.features?.enable_sharepoint_import}` (2 lines). **Must not go back to the OneDrive flags** — see the `main.py` entry above. Detector: `grep -n "enable_sharepoint_import" src/lib/components/workspace/Knowledge/KnowledgeBase.svelte`
- `src/lib/apis/users/index.ts` — `getCredentialStatus` / `setCredentialOptIn` / `deleteCredential` + `CredentialStatus` type against `/users/user/credentials/*` (~48 lines). Detector: `grep -n "credentials/" src/lib/apis/users/index.ts`
- `src/lib/components/chat/Settings/Account.svelte` — import + `{#if $config?.features?.enable_ldap_credential_store}` block rendering `CredentialStore` (6 lines).
- `src/lib/components/admin/Settings/Documents.svelte` — force-retrieval toggle (16 lines).
- `src/lib/components/admin/Settings/CodeExecution.svelte` — pyodide prompt textarea (24 lines).
- `src/lib/i18n/locales/{de-DE,en-US}/translation.json` — force-retrieval label/tooltip keys.
- `src/lib/i18n/locales/de-DE/translation.json` — 11 credential-store keys (`Stored network password`, `Allow storing my password`, …). de-DE only; the other locales fall back to the English key text.

---

## 7. Overlay — deep fork modifications of upstream files

| Path | Fork diff vs v0.10.2 | Reason |
|---|---|---|
| `backend/open_webui/retrieval/utils.py` | ~1029 lines | RAG enhancements on the 0.10.2 base: `tokenize_for_bm25`, `ScoringBM25Retriever` (replaces `BM25Retriever.from_texts`), `extract_matched_keywords` citations, embedding retry framework (`embedding_with_retry`, error classes), `enable_reranking` gate through the whole chain, `filter_results_by_relevance`, `merge_rag_settings`, `*_with_settings` wrappers, per-KB override resolution in `get_sources_from_items`. **Upstream's native pgvector hybrid path (`query_doc_with_native_hybrid_search`) and the external-KB branch are preserved untouched** — fork logic only extends the local-collection fallback path. |
| `backend/open_webui/routers/knowledge.py` | ~932 lines | SharePoint import block (`/{id}/sharepoint/*`, `/sharepoint/sites*`) + `/{id}/reindex`; write access guarded by upstream `is_external_knowledge`; size limit via `Config.get('rag.sharepoint.import_max_total_size_mb')`. Per-KB rag_settings ride the standard `meta` update endpoint (no separate route). **Backend-agnostic since 2026-07-31:** `_get_microsoft_access_token` is gone; all 9 call sites now do `graph = await get_sharepoint_backend(request, user, db)`. `_translate_graph_error` is async and per-backend, and drops the stored credential on a genuine on-prem 401. `_persist_sharepoint_source` records `backend`; re-import against a mismatching backend returns 409. Detector: `grep -n "get_sharepoint_backend\|SHAREPOINT_BACKEND" backend/open_webui/routers/knowledge.py` |
| `backend/open_webui/models/knowledge.py` | ~53 lines | `RagSettings` + `KnowledgeMeta` models, `meta` on `KnowledgeForm`, deprecated `update_knowledge_data_by_id`, `update_knowledge_meta_by_id`. |
| `backend/open_webui/utils/middleware.py` | ~150 lines | **KB-deterministic-inject** (marker `# FORK: KB-deterministic-inject`): force-retrieval gate on both injection sites, adapted to 0.10.2 `== 'legacy'` semantics (`function_calling` is now `null\|'native'\|'legacy'`; upstream injects only on `legacy`); `folder_knowledge` sidecar kept dual-path (upstream `tools.py:518` consumes it natively). **Per-level RAG settings wiring** (marker `# FORK: per-level RAG settings`): global < user < model cascade + per-KB overrides passed to `get_sources_from_items` (restored — lost in the 0.9.6 replay). **Pyodide prompt override** at both append sites. **`__sharepoint__` in `extra_params`** (2 of the 3 sites — the outlet-filter site gets no credentials, matching how `__oauth_token__` is already handled): tools receive a ready client, never a credential. Detectors: `grep -n "FORK:" backend/open_webui/utils/middleware.py` |
| `src/lib/apis/knowledge/index.ts` | ~411 lines | SharePoint + reindex + per-KB API client functions. |
| `src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` | ~387 lines | SharePoint import UI, per-KB RAG settings, reindex, preview split, flicker fix — all gated off for external KBs (`meta.source === 'external'`). |
| `src/lib/components/workspace/Models/ModelEditor.svelte` | ~56 lines | Per-model RAG settings section (`info.meta.rag_settings`). |
| `src/lib/components/chat/Messages/Citations/CitationModal.svelte` | ~73 lines | Extended citation metadata display (matched keywords). |
| `src/lib/components/chat/Settings/General.svelte` | ~54 lines | User-level RAG settings. |
| `src/lib/utils/onedrive-file-picker.ts` | ~113 lines | Graph API adjustments. |

**Resolved by 0.10.2 (removed from this inventory):**
- Chroma `has_collection` fix — upstream commit `15d96b1f2` (the fork copy had already been lost in the 0.9.6 replay).
- `ddgs` requirements pin — upstream bumped to 9.14.4; fork diff was already gone (stale entry).
- `folder_knowledge` sidecar consumption — upstream-native in `utils/tools.py` (sidecar *population* remains fork-conditional, see middleware overlay).

## 8. Binary / static overlays

- `backend/open_webui/static/favicon.ico`, `favicon.png` — fork favicons (new branding pending in main-tree WIP).
- `static/pyodide/pyodide-lock.json` — regenerated by build; prefer `--theirs` then rebuild.

## 9. Customer branches currently in flight

| Customer | Branch | Notes |
|---|---|---|
| Stolley | `feature/sharepoint-kb-integration` | Cut `release/stolley-<date>` **before** merging `feature/owui-0.10.2` to `main`. |
| Stadtbau | `main` (at prior main-HEAD) | Cut `release/stadtbau-<date>` before the merge to `main`. |
| PV | `customer` remote on net-solution-GmbH | Push target: `customer`, not `origin`. |

## 10. Regeneration recipe

```bash
git diff v0.10.2..HEAD --stat  # walk, update counts, categorize new files
# Detectors in §6 must all hit; run them in one pass:
grep -rn "FORK:" backend/open_webui/{config.py,utils/middleware.py}
```

The alembic-merge skill refuses to complete a merge PR without this file being updated in the same commit.
