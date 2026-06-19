# Upstream v0.9.6 Merge Triage

> Fork base (merge-base) = upstream **v0.9.2** (`8dae237a0`). Target = upstream **v0.9.6** (`1a97751e3`).
> Question tested: **Does upstream 0.9.6's KB-sync / RAG work obsolete our fork's KB + RAG + SharePoint stack?**
> Method: every claim verified at source via `git show v0.9.6:<path>` / `git diff v0.9.2..v0.9.6` / `git diff v0.9.2..HEAD`. Each group ran through an adversarial-verify pass.

---

## 1. Executive Summary

**Verdict: NO — 0.9.6 does NOT obsolete the fork's KB/RAG/SharePoint work. The user's redundancy hypothesis is DISPROVEN across every dimension.**

What 0.9.6 calls "sync" is **client-driven LOCAL-folder mirroring** (`/sync/diff`, `/sync/cleanup`): the browser supplies a manifest of a locally-picked folder (`showDirectoryPicker()`, SHA-256 computed client-side), the server diffs it against a NEW internal directory tree, and the **browser** does the upload. There is **no server-side connector, no scheduler, no remote credentials, no OAuth source linking, no re-index-on-source-change**. A full `git ls-tree v0.9.6` for `connector|sync|sharepoint|onedrive|googledrive|scheduler|cron` returns **zero** added files.

Likewise, upstream added **no native hybrid search, BM25, per-KB/per-query RAG settings, reranking, or citation features** — all of those RAG primitives already existed in the shared v0.9.2 base and are byte-identical-in-presence across v0.9.2 / v0.9.6 / HEAD (so they are neither fork-new nor 0.9.6-new).

The real friction is **collision, not obsolescence**: 0.9.6 ran a major KB-UI redesign (internal directory tree + local-folder sync + pending-file polling) plus security hardening in `retrieval/utils.py` and a global `PersistentConfig -> ConfigVar` config rename — all landing in the **same files** the fork edits.

**Headline verdicts (10 groups):**

| # | Group | Final verdict |
|---|-------|---------------|
| 1 | sharepoint-graph-kb-import | **APPLY** |
| 2 | rag-enhancements-retrieval-utils | **APPLY** |
| 3 | kb-deterministic-inject | **APPLY** |
| 4 | per-kb-rag-settings-ui | **REWORK** |
| 5 | processing-dashboard | **APPLY** |
| 6 | pseudonymizer-hooks | **DISCARD** (phantom — no fork code exists) |
| 7 | access-grant-sharing | **SPLIT** |
| 8 | openai-strict-schema-fix | **APPLY** |
| 9 | schema-validation-startup | **SPLIT** |
| 10 | config-env-injections | **SPLIT** |
| 11 | fork-migrations-chain | **APPLY** |
| 12 | ci-tooling-docs | **SPLIT** |

Nothing the fork built was made redundant by 0.9.6. The only true DISCARD is `pseudonymizer-hooks`, and that is DISCARD because **the fork change does not exist** (a stale FORK_CHANGES.md entry), not because upstream covers it.

---

## 2. Upstream 0.9.6 KB-sync / RAG Findings (what is genuinely new)

### KB / knowledge area
- **Internal KB directory/folder tree** — new `knowledge_directory` table (self-referencing `parent_id`), `knowledge_file.directory_id` FK. Evidence: migration `3c9b0ca343fd_add_knowledge_directory_table.py`; `models/knowledge.py` `+KnowledgeDirectory`.
- **Directory CRUD + breadcrumbs + file-move endpoints** — `/dirs/create`, `/dirs/{id}/update`, `/dirs/{id}/delete`, `/file/move`. Evidence: `routers/knowledge.py` diff L671-774.
- **Client-driven LOCAL-folder sync** — `/{id}/sync/diff` + `/{id}/sync/cleanup`. Compares a browser-supplied manifest (`FileManifestEntry{filename,path,checksum=SHA-256}`) against the internal dir tree. **NOT a remote connector.** Evidence: `routers/knowledge.py` diff L385-511; frontend `KnowledgeBase.svelte` v0.9.6 L598-732.
- **Pending-files endpoint** — `/{id}/files/pending` (optional SSE stream, polls ~3-5s) surfacing files still processing before they are linked. Evidence: `routers/knowledge.py` diff L172-228; `models/files.py` `get_pending_files_for_knowledge`.
- **`tools/knowledge_fs.py`** (1109 L) — filesystem-like `ls/cat/grep/find` over KB files for AI models (agentic, not sync).
- **`ENABLE_KB_EXEC` + `kb_exec`/`grep_knowledge_files` builtin tools** — upstream's OWN agentic, tool-driven, default-OFF take on native-FC knowledge access. Evidence: `utils/tools.py get_builtin_tools()`; `env.py:786` `ENABLE_KB_EXEC='False'`.
- **Content search in file listing** — `filter.include_content` searches `File.data['content']` via `->>`.
- **Batch file-add** with per-file `directory_id` mapping.
- **Frontend redesign** — new `DirectoryRow.svelte` (191L), `KnowledgeBreadcrumbs.svelte` (89L), `NewDirectoryModal.svelte` (79L); `KnowledgeBase.svelte +554`, `Files.svelte +167`, `AddContentMenu.svelte +32`; file rename, copy-KB-ID, "File content" search toggle.

### RAG / retrieval area
- **No new RAG features.** `retrieval/utils.py` 0.9.6 delta is ~+78 net lines of churn, adding exactly **one** new def: `_is_safe_collection_name`.
- **Security hardening (the real overlap):** `_SAFE_COLLECTION_NAME_RE`/`_is_safe_collection_name` (Milvus expr-injection guard), `ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS` deny-by-default, `BYPASS_RETRIEVAL_ACCESS_CONTROL` gating on file/collection fallbacks, cross-tenant `collection_name` substitution guard, redirect-SSRF fix in `get_content_from_url` (`allow_redirects=AIOHTTP_CLIENT_ALLOW_REDIRECTS` + YouTube fast-path), no-embedding-model `ValueError` guard.
- **`PersistentConfig -> ConfigVar` rename** across all of `config.py` (v0.9.2: 359 PersistentConfig / 0 ConfigVar; v0.9.6: 0 / 361). Every RAG config key already existed in v0.9.2.
- **Native-FC KB-injection behavior UNCHANGED** — `middleware.py` still SKIPS RAG injection on native function-calling (`function_calling != 'native'` gate at v0.9.6 middleware.py:2474 folder, :2488 model_knowledge). Upstream's only edit there is access-control: `folder.data['files']` -> `allowed_files = await get_accessible_folder_files(...)`.
- **`rag_template` became ASYNC** (`async def rag_template(template, context, query)` in `utils/task.py:259`; callers now `await`). `apply_system_prompt_to_body` also async.
- **Tooling improvements** — OpenAPI `$ref` (oneOf/anyOf/allOf) resolution, HTTP-method filtering, param merging, URL-encoding; shared `build_tool_server_headers()` + `oauth_2.1` auth; configurable `MCP_INITIALIZE_TIMEOUT`.
- **Infra additions (unrelated):** Valkey vector backend (`VALKEY_*`), Linkup/Brave web-search context, MinerU file-extensions config, profile-image vars.
- **NOT fixed upstream:** the OpenAI strict-mode empty-`properties` schema bug — our fork's fix remains necessary.

---

## 3. Decision Matrix

| Group | Final verdict | Conf. | Conflict risk | Alembic impact | Upstream overlap (1 line) |
|-------|---------------|-------|---------------|----------------|---------------------------|
| sharepoint-graph-kb-import | APPLY | 93 | injection | NONE | No upstream remote connector; only file-level collision in `AddContentMenu`/`knowledge.py` (disjoint routes). |
| rag-enhancements-retrieval-utils | APPLY | 93 | overlay | NONE | No RAG feature overlap; security rewrite of shared `get_sources_from_items` must be re-merged. |
| kb-deterministic-inject | APPLY | 90 | overlay | NONE | Native-FC skip unchanged; `rag_template` went async + `allowed_files` access-filter must be re-grafted. |
| per-kb-rag-settings-ui | REWORK | 93 | overlay | NONE | +524L KB-UI redesign rewrote the surrounding code; fork overlay must be reshaped, not text-merged. |
| processing-dashboard | APPLY | 96 | additive | Adds `processing_task` table (fork node) | None; all 7 files absent upstream. Cross-group dep on RAG tracker. |
| pseudonymizer-hooks | DISCARD | 95 | additive | NONE | Phantom group — no fork code exists; stale FORK_CHANGES.md entry. |
| access-grant-sharing | SPLIT | 93 | overlay | Same-node body conflict in `f1e2d3c4b5a6` | ACL is upstream-legacy; only the migration idempotency rewrite is fork-real. |
| openai-strict-schema-fix | APPLY | 97 | injection | NONE | Upstream never fixed empty-`properties`; clean re-inject. |
| schema-validation-startup | SPLIT | 93 | overlay | NONE | Validation layer additive (APPLY); JSONField guard overlays rewritten UnicodeText body (REWORK). |
| config-env-injections | SPLIT | 93 | injection | NONE | env.py clean additive; config.py needs `PersistentConfig -> ConfigVar` rewrite + 2 gotchas. |
| fork-migrations-chain | APPLY | 93 | additive | Two heads -> `alembic merge heads` | None; fork recovery shims absent upstream, disjoint tables. |
| ci-tooling-docs | SPLIT | 93 | additive | NONE | Net-new files (APPLY); CI-disable must retarget upstream's restructured workflows (REWORK). |

---

## 4. Per-group Detail

### 4.1 sharepoint-graph-kb-import — **APPLY** (conf. 93, injection)
**Rationale.** 0.9.6 has no SharePoint/OneDrive/Graph remote-source connector. `graph_client.py` (540L), `SharePointPicker.svelte`, `test/sharepoint/*` are fork-new ("exists on disk but not in v0.9.6"). `onedrive-file-picker.ts` exists in all three but the v0.9.2..v0.9.6 diff is EMPTY; the fork's delta (`getGraphToken`, `verifyGraphAccess`, `mode:'folders'`) is purely additive. Upstream "sync" is local-folder mirroring, not remote import.

**Upstream-overlap evidence.** File-level collisions only, never feature redundancy: (a) `AddContentMenu.svelte` — fork's "Import from SharePoint" button + `showSharePointImport` prop vs upstream's "New directory"/"Reset" + `onReset` at the same `{Add text content}` anchor. (b) `routers/knowledge.py` — heavily restructured upstream (+554 region) but **zero endpoint-path collision** with the 11 fork SharePoint routes (all under `/{id}/sharepoint/*`, `/sharepoint/sites/*`, `/sharepoint/drives/*`, plus `/{id}/reindex` distinct from pre-existing `/reindex` + `/metadata/reindex`). (c) `models/knowledge.py` — **hard dependency**: `_persist_sharepoint_source` requires the fork's `meta` field on `KnowledgeForm`, which upstream 0.9.6 `KnowledgeForm` (L160-163) lacks.

**Adversarial verify.** AGREE. Refined one action: verify confirmed v0.9.6 has **no `data` column** in either the Knowledge ORM table (L47-56) or `KnowledgeModel` (L78-92), yet upstream's own `update_knowledge_data_by_id` (L758) still writes `.values(data=data)` against the non-existent column — i.e. upstream's method is broken dead legacy that would raise. The fork's no-op deprecation is the **correct** state for the v0.9.6 schema; keep it and route persistence through `update_knowledge_by_id(meta=...)`. This strengthens APPLY.

**Merge actions.**
- Take `graph_client.py`, `SharePointPicker.svelte`, `test/sharepoint/*`, `onedrive-file-picker.ts` **verbatim from HEAD** (fork-new / empty upstream diff).
- `routers/knowledge.py`: start from the 0.9.6 file, **re-inject** the SharePoint block additively — imports, the pydantic Form/Result models, helpers (`_import_single_graph_file`, `_import_graph_files`, `_persist_sharepoint_source`, `_assert_knowledge_write_access`), and the 11 endpoints. Routes are disjoint from `/sync/*` and `/dirs/*`.
- `models/knowledge.py`: **re-add** `meta: Optional[dict] = None` to `KnowledgeForm` (dropped upstream) — required for source persistence. Keep the fork's no-op `update_knowledge_data_by_id` (upstream's is broken vs the v0.9.6 schema).
- `AddContentMenu.svelte`: hand-merge — keep BOTH upstream (`onReset`, New directory, Reset, `NewFolderAlt`/`GarbageBin`/`ArrowUturnLeft` imports) AND fork (`showSharePointImport`, Import-from-SharePoint button); place the SharePoint button after "Add text content", before the new Reset block.
- Post-merge: run `test/sharepoint/test_graph_client.py` + `test_sharepoint_import.py`.

### 4.2 rag-enhancements-retrieval-utils — **APPLY** (conf. 93, overlay)
**Rationale.** Nothing in 0.9.6 obsoletes this. All RAG primitives (BM25Retriever, EnsembleRetriever/RRF, `ENABLE_RAG_HYBRID_SEARCH`, `RerankCompressor`, enriched texts, `RELEVANCE_THRESHOLD`) already existed in v0.9.2 (`retrieval/utils.py` L17-19, L328-543) and are unchanged across all three refs. Fork-exclusive and live: NEW FILE `retrieval/models.py` (RAGQuerySettings + merge_rag_settings), NEW FILE `RagSettingsModal.svelte` (255L), 9 `test/retrieval/*` files, and 13-14 fork-only defs in `utils.py` (`ScoringBM25Retriever`, `query_doc/collection_with_hybrid_search_settings`, `get_sources_from_items_with_settings`, `EmbeddingError/PartialEmbeddingError/RateLimitError`, `embedding_with_retry`, `cleanup_memory`, `tokenize_for_bm25`, `extract_matched_keywords`, `filter_results_by_relevance`, `merge_rag_settings`).

**Upstream-overlap evidence.** Pure structural/security collision. The fork modified the BASE `get_sources_from_items` **in-place** (HEAD L1949) — the exact function `middleware.py:74` imports and `middleware.py:2132` calls — which upstream 0.9.6 rewrote with 13 access-control/injection guards the fork entirely lacks (HEAD grep: `_is_safe_collection_name=0`, `BYPASS_RETRIEVAL_ACCESS_CONTROL=0`, `ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS=0`, `allow_redirects=0`, "No embedding model is loaded"=0; v0.9.6=13 hits). The security gap is on the **live path**.

**Adversarial verify.** AGREE — could not refute. Confirmed the APPLY-**with-mandatory-security-reinjection** caveat must NOT be downgraded to clean APPLY.

**Merge actions.**
- Additive (clean): `retrieval/models.py`, `RagSettingsModal.svelte`, all 9 `test/retrieval/*` — take as-is from HEAD.
- **`utils.py`: take upstream 0.9.6 as the base.** Re-inject the 13-14 fork-only top-level defs (paste cleanly — absent upstream).
- **Hand-merge** the per-KB settings logic into upstream's hardened `get_sources_from_items`, preserving EVERY security guard. Layer fork edits onto `get_content_from_url` (after upstream's SSRF/YouTube fix; import `AIOHTTP_CLIENT_ALLOW_REDIRECTS`) and `get_embedding_function` (on top of the no-embedding `ValueError` guard).
- Verify config keys still resolve (note the `ConfigVar` rename; `ENABLE_RAG_RERANKING` is fork-only and must survive config.py merge).
- Run `pytest backend/open_webui/test/retrieval/` as the regression gate; confirm `middleware.py:74` import resolves.

### 4.3 kb-deterministic-inject — **APPLY** (conf. 90, overlay)
**Rationale.** `RAG_NATIVE_FC_FORCE_RETRIEVAL` deterministic injection + `folder_knowledge` sidecar has no upstream equivalent. v0.9.6 middleware still SKIPS RAG on native FC (`!= 'native'` gate at :2474 folder / :2488 model). `RAG_NATIVE_FC_FORCE_RETRIEVAL` = 0 hits in v0.9.6 (exists only at HEAD config.py:2852). `ENABLE_KB_EXEC` (env.py:786, default False) is agentic/tool-driven — a different philosophy, not a replacement.

**Upstream-overlap evidence.** Two real API changes hit the same regions: (a) access-control — `allowed_files = await get_accessible_folder_files(folder.data['files'], user)` (middleware.py:2473, import L76); the native-FC gate itself is unchanged. (b) `rag_template` became ASYNC (`utils/task.py:259`) with awaited callers (middleware.py:983/989), while the fork kept it SYNC and added a 4th positional `knowledge_bases` param + `{{KNOWLEDGE_BASES}}` replacement.

**Adversarial verify.** AGREE — all core claims verified. APPLY (overlay), not clean injection.

**Merge actions.**
- middleware folder block: rebase the fork's `force_retrieval = getattr(request.app.state.config,'RAG_NATIVE_FC_FORCE_RETRIEVAL',True); if function_calling != 'native' or force_retrieval:` onto upstream's new `allowed_files` (use `*allowed_files`, NOT `*folder.data['files']` — keep access-control). Keep the `if function_calling == 'native': metadata['folder_knowledge'] = allowed_files` sidecar.
- middleware model_knowledge gate: re-apply the same `or force_retrieval` over the unchanged upstream gate.
- `utils/task.py`: re-graft 4th param onto the async signature -> `async def rag_template(template, context, query, knowledge_bases: str = ''):`, keep `await prompt_template(...)`, add the `{{KNOWLEDGE_BASES}}` replace.
- Fork call sites (`apply_source_context_to_messages`, `streaming_chat_response_handler`): add `await` to `rag_template(...)`.
- config.py: re-add `RAG_NATIVE_FC_FORCE_RETRIEVAL` (+ sibling `ENABLE_RAG_RERANKING`) as `ConfigVar`. main.py: re-add the state-wiring line + import. retrieval.py router: re-insert into `get_rag_config`, `ConfigForm` (upstream uses `bool | None`), and the setter (anchors at v0.9.6:427/637/724).
- Documents.svelte + i18n: re-add the toggle and 2 keys.
- Re-run `test_native_fc_force_retrieval.py`.

### 4.4 per-kb-rag-settings-ui — **REWORK** (conf. 93, overlay)
**Rationale.** All three fork sub-features survive (per-KB RAG settings UI, SharePoint import UI, Reindex button) — none obsoleted — but upstream's +524-line KB redesign rewrote the exact surrounding code the fork's 352-line overlay sits on. Must be **reshaped onto the new structure** (injection), not text-merged. `RagSettingsModal.svelte` absent upstream; v0.9.6 `apis/knowledge/index.ts` has 0 hits for `reindexKnowledgeById`/`sharepoint`; v0.9.6 `KnowledgeBase.svelte` has 0 hits for `rag_settings`.

**Upstream-overlap evidence (4 verified collisions).** (a) `AdjustmentsHorizontal` imported on BOTH sides — fork for the RAG button, upstream (`:71`, used `:1328`) for the search "File content" toggle -> dedupe. (b) `getItemsPage` rewritten to `searchKnowledgeFilesById(...currentDirectoryId, includeContent)` but still does the unconditional `fileItems = null; fileItemsTotal = null` reset (`:178-179`) — the fork's flicker fix (commit `98cff8eb2`, `if (fileItems === null)`) must be re-applied onto the NEW body. (c) `onUpload` gained a `new_directory` branch (`:1360`) — re-inject `else if (data.type === 'sharepoint')`. (d) `AddContentMenu` shared anchor (coordinate with 4.1).

**Adversarial verify.** AGREE — REWORK stands; plain APPLY impossible (collisions real), DISCARD impossible (fork-exclusive).

**Merge actions.**
- Start from upstream v0.9.6 `KnowledgeBase.svelte`; re-inject the 3 features additively.
- Imports: add fork-only (`listSharePointFolder`/`importSharePointFile`/`persistSharePointSource`/`reimportSharePointFolder`/`reindexKnowledgeById`, `openOneDrivePicker`, `SharePointPicker`, `RagSettingsModal`, `ArrowPath`, `Textarea`). **Dedupe `AdjustmentsHorizontal`** — keep the single upstream import.
- State + handlers: add fork vars/handlers on top of upstream's (which already has `includeContent`, `currentDirectoryId`, `showNewDirectoryModal`, `showResetConfirm`).
- **Re-apply commit `98cff8eb2`** onto upstream's `searchKnowledgeFilesById` body (replace the unconditional null-reset with the guarded form); reconcile against upstream pending-file polling so the two flicker mechanisms don't double-reset.
- Toolbar: change the write-access wrapper to `flex gap-1`; inject RAG button before Access, Reindex after.
- Modals: add `<SharePointPicker>`, Reindex `<SyncConfirmDialog>`, `<RagSettingsModal ragSettings={knowledge.meta?.rag_settings ?? {}}>`.
- `onUpload`: re-inject the `sharepoint` branch; add `showSharePointImport={...onedrive_business}` prop. SharePoint source banner: inject `{#if knowledge?.meta?.sharepoint_source}`.
- `npm run lint` + `npm run build`; smoke-test RAG save, SharePoint open, Reindex, non-flicker.

### 4.5 processing-dashboard — **APPLY** (conf. 96, additive)
**Rationale.** Entirely fork-exclusive; zero upstream equivalent. All 7 core files ABSENT in v0.9.6 (`git cat-file -e v0.9.6:<path>` fails for `routers/processing.py`, `models/processing.py`, the `a8f52d3c1e7b` migration, `apis/admin/processing.ts`, `stores/processing.ts`, `components/admin/Processing.svelte`, `routes/(app)/admin/processing/+page.svelte`). v0.9.6 `main.py` has no processing router (its 4 "processing" hits are log strings — lines 1503/2015/2046/2060); v0.9.6 `db.py` = 0 processing refs. Upstream's per-KB `/{id}/files/pending` is in-flight file surfacing, NOT an admin-wide task store with status/stage/cancel/retry.

**Adversarial verify.** AGREE. Cross-group dependency confirmed load-bearing: the `ProcessingTaskTracker` cancellation backend lives in `retrieval/utils.py` (L227/237/1778, `ProcessingCancelledException`) and is owned by the **RAG-overlay group** — without that group re-applying the tracker, the dashboard's cancel/retry buttons have no backend effect. Keep flagged.

**Merge actions.**
- Re-add the 7 fork-new files + `test/processing/*` verbatim.
- Inject into `main.py`: add `processing,` to the router import block + `app.include_router(processing.router, prefix='/api/v1/admin/processing', tags=['processing'])` (additively — line numbers shifted by upstream's new routers).
- Inject into `internal/db.py`: `from open_webui.models.processing import ProcessingTask` + add to `validate_all_schemas` list (rides with the schema-validation group).
- Migration `a8f52d3c1e7b` (down_revision `56359461a091`) carries forward; resolved by `alembic merge heads` (see §5).
- **Flag cross-group dep:** RAG group must re-apply `ProcessingTaskTracker`.
- Run `test/processing/*` (esp. `test_processing_router_registration.py`); verify `/admin/processing` nav still links.

### 4.6 pseudonymizer-hooks — **DISCARD** (conf. 95, additive)
**Rationale.** **PHANTOM group — there is no pseudonymizer code in the fork.** Repo-wide `git grep -il pseudonym` at HEAD returns exactly ONE file: `docs/FORK_CHANGES.md` (the inventory doc itself); ZERO in v0.9.2 and v0.9.6. All three FORK_CHANGES detectors return empty against the fork delta. The grep tooling works (it finds `sharepoint` in 7 backend files), so these are true negatives. DISCARD is proven by **absence of the fork change**, not by upstream coverage. The config/retrieval edits FORK_CHANGES attributes here are actually RAG-settings + SharePoint config (other groups).

**Adversarial verify.** AGREE — DISCARD survives. One refinement: FORK_CHANGES.md line 135 conflates `ProcessingTaskTracker` (a REAL fork feature = the Processing dashboard) with the phantom pseudonymizer. Cleanup must surgically delete ONLY the "+ pseudonymizer" mention and the `|pseudonymizer` token, PRESERVING the `ProcessingTaskTracker`/`process_file` note.

**Merge actions.**
- Take ZERO pseudonymizer action on `middleware.py`/`retrieval.py`/`config.py`.
- Clean `docs/FORK_CHANGES.md`: remove the stale pseudonymizer claims (lines 116, 123, the `|pseudonymizer` token on line 136), keeping the genuine ProcessingTaskTracker record.
- If a pseudonymizer is actually wanted, track it as net-new work — it is not part of the v0.9.2..HEAD delta.

### 4.7 access-grant-sharing — **SPLIT** (conf. 93, overlay)
**Rationale.** Mostly **misattribution**: the AccessGrants ACL system is **upstream-legacy**, not fork-original. `models/access_grants.py` fork diff v0.9.2..HEAD is EMPTY; `has_access`/`get_accessible_resource_ids`/`has_permission_filter` present identically in v0.9.2 and v0.9.6. The `routers/knowledge.py` ACL lines only CALL the pre-existing API (belongs to the SharePoint group). The `utils/tools.py +9` is the OpenAI empty-properties fix (belongs to group 4.8). The **only genuine fork piece** is migration `f1e2d3c4b5a6` (commit `2f25363c8` idempotency rewrite).

**Upstream-overlap evidence.** `f1e2d3c4b5a6` has the SAME revision ID and SAME `down_revision` (`8452d01d26d7`) in all three refs — a **same-node body conflict**, not a divergent head. Fork and upstream INDEPENDENTLY rewrote `upgrade()` for idempotency; fork's is strictly more robust (cross-dialect `_table_exists`/`_column_exists`, `ON CONFLICT DO NOTHING`/`INSERT OR IGNORE`, structured logging). Upstream's adds `insp.clear_cache()` + column-existence guards. `downgrade()` identical.

**Adversarial verify.** AGREE — every claim survives source check. SPLIT stands.

**Merge actions.**
- Take upstream `models/access_grants.py` verbatim (fork made zero changes).
- Resolve `knowledge.py` ACL inside the SharePoint group; resolve `tools.py` inside group 4.8 — not here.
- **Migration:** keep the FORK `upgrade()` body, but **fold in** upstream's `insp = sa.inspect(conn); insp.clear_cache()` before per-table column checks. Keep revision/down_revision unchanged. No `downgrade()` action.
- Verify `alembic upgrade head` on fresh SQLite AND a Postgres DB that already ran the v0.9.2 form (idempotency re-run).
- Reclassify in FORK_CHANGES.md (ACL is upstream-legacy; tools.py/knowledge.py misattributed).

### 4.8 openai-strict-schema-fix — **APPLY** (conf. 97, injection)
**Rationale.** Both fork hunks inject empty `properties: {}` into parameter-less object schemas so OpenAI strict-mode FC accepts them. Upstream never fixed this. v0.9.6 `clean_openai_tool_schema` (L776-784) = deepcopy + `if 'parameters' in cleaned_spec: clean_properties(...)`. v0.9.6 `clean_properties` (L749-773) only recurses into pre-existing properties (`if 'properties' in schema:`) and its "fix missing type" branch requires `'type' not in schema` (a bare `{type:object}` is skipped) — so the bug is provably unfixed. v0.9.6 `mcp/client.py list_tool_specs` passes `tool.inputSchema` unmodified (L95-97).

**Adversarial verify.** AGREE — clean additive injection, anchors verbatim in 0.9.6.

**Merge actions.**
- `tools.py`: re-inject the empty-properties block after `cleaned_spec = copy.deepcopy(spec)`, before `if 'parameters' in cleaned_spec:` (operate on `cleaned_spec`, not `spec`).
- `mcp/client.py`: re-inject the guard between `inputSchema = tool.inputSchema` and the `# TODO: handle outputSchema` comment (separate from the `MCP_INITIALIZE_TIMEOUT` hunk).

### 4.9 schema-validation-startup — **SPLIT** (conf. 93, overlay)

> **Update (2026-06): part (A) DROPPED.** The startup validation layer was found to be dead code — the `main.py` lifespan call was never wired in during the replay, so `validate_all_schemas` was never invoked. It duplicated Alembic's guarantee, covered a single model, and hard-coupled db.py to the processing feature. **Deleted** from db.py; do NOT re-apply. Only part (B), the JSONField guard, remains. See FORK_CHANGES.md › `internal/db.py`.

**Rationale.** Two independent changes. **(A) Startup schema-validation layer = ~~APPLY~~ DROPPED:** `SchemaValidationError`/`validate_model_schema`/`validate_all_schemas` in `db.py` had no upstream equivalent and no live caller — removed rather than re-applied. **(B) JSONField dict/list guards = REWORK:** upstream 0.9.6 DELETED the peewee layer (so the fork's `python_value` guard targets a now-gone method — drop it) and rewrote JSONField `impl Text -> UnicodeText` with one-line bodies — so the `process_result_value` guard must be re-applied onto the new one-liner.

**Note (correction).** `get_async_db_context`, async engine, SSL normalization, Windows SelectorEventLoop are **upstream-legacy** (pristine in v0.9.2, retained in v0.9.6) — NOT fork-new. FORK_CHANGES.md's "~105 lines async DB" attribution is wrong; the real fork db.py delta is only the JSONField guards + the appended validation block.

**Adversarial verify.** AGREE — SPLIT survives. Coupling confirmed: `validate_all_schemas` imports the fork-only `ProcessingTask`, so it MUST merge with the processing feature or startup crashes on import. v0.9.6 `process_bind_param` still `json.dumps` unconditionally, so the read-side native-JSON guard remains needed.

**Merge actions.**
- Take upstream JSONField verbatim (UnicodeText one-liners); drop the fork's `python_value`/`db_value` guards.
- Re-apply ONLY the `process_result_value` dict/list passthrough onto upstream's body (`if isinstance(value,(dict,list)): return value` then `json.loads`).
- ~~Append the validation block / wire `main.py`~~ — **DROPPED** (part A removed, see update note above). Do not re-add the validation block or any `validate_all_schemas` call.
- Smoke: JSONField round-trip on a Postgres native-JSON column returns dict/list.

### 4.10 config-env-injections — **SPLIT** (conf. 93, injection)
**Rationale.** All 8 fork-new names absent in v0.9.6 and still consumed at HEAD (no DISCARD). Splits by file. **(A) env.py = APPLY:** `FORK_VERSION_SUFFIX` + the 4 `EMBEDDING_RETRY_*` plain vars are name-disjoint from upstream's env additions; paste as-is. **(B) config.py = REWORK:** v0.9.6 migrated the whole layer `PersistentConfig -> ConfigVar` (0 PersistentConfig hits; import `from open_webui.internal.config import (AppConfig, ConfigVar)`), so the fork's three `PersistentConfig(...)` fields would `NameError` verbatim — rewrite as `ConfigVar(...)`.

**Upstream-overlap evidence (2 gotchas).** (1) `ONEDRIVE_CLIENT_ID_BUSINESS`: v0.9.6 KEEPS it plain `os.getenv` (`:991`) and derives `ENABLE_ONEDRIVE_BUSINESS` via `bool(ONEDRIVE_CLIENT_ID_BUSINESS)` (`:996`). The fork wraps it as a config object (always truthy) — so the bool line MUST become `bool(ONEDRIVE_CLIENT_ID_BUSINESS.value)`, else business mode silently forces True. (`MICROSOFT_CLIENT_ID` is a ConfigVar at v0.9.6:3509 so `.value` fallback is valid.) (2) `DEFAULT_RAG_TEMPLATE`: v0.9.6 ships the old `### Task:` template (`:1420`, `{{CONTEXT}}` only); the fork adds `{{KNOWLEDGE_BASES}}`+`{{QUERY}}`, consumed at `utils/task.py:294 .replace()` — re-apply the fork template (coupled to the inject overlay), do NOT take upstream's.

**Adversarial verify.** AGREE — SPLIT survives; both gotchas verified.

**Merge actions.**
- env.py: re-add `FORK_VERSION_SUFFIX` (after VERSION) + the 4 `EMBEDDING_RETRY_*` vars (after `RAG_EMBEDDING_TIMEOUT`).
- config.py: rewrite `RAG_NATIVE_FC_FORCE_RETRIEVAL`, `SHAREPOINT_IMPORT_MAX_TOTAL_SIZE_MB`, `ENABLE_RAG_RERANKING` as `ConfigVar(...)`.
- `ONEDRIVE_CLIENT_ID_BUSINESS`: keep the fork's richer def as `ConfigVar`; patch `ENABLE_ONEDRIVE_BUSINESS` to use `.value`.
- `DEFAULT_RAG_TEMPLATE`: re-apply the fork template (with the inject overlay).
- Post-merge: `python -c "import config"` (no NameError); confirm main.py consumers resolve.

### 4.11 fork-migrations-chain — **APPLY** (conf. 93, additive)
**Rationale.** All 6 fork files are fork-exclusive (`git cat-file -e v0.9.6:<path>` ABSENT for `_fork_helpers.py` + 5 versions). Drifted-DB recovery shims (idempotent backfills/repairs) with no upstream counterpart. The fork chain branches off the shared head `56359461a091` down its own path; upstream branches off the SAME node — so a merge yields TWO heads.

**Upstream-overlap evidence.** Fork backfills target calendar/automation/shared_chat tables + chat/note/processing_task columns + access_grant/skill/user repairs — all DISJOINT from upstream's 4 new migrations (pinned_note, ix_memory_user_id, knowledge_directory, legacy-PK promotion). The ONLY contact point is `note.is_pinned`: fork `f1b2c3d4e5f6:61` idempotently re-adds it; upstream `4de81c2a3af1:70` migrates rows into `pinned_note` then DROPS the column. Both guarded/idempotent -> worst case a harmless redundant empty column, ordering-dependent, no hard fail.

**Adversarial verify.** AGREE — redundancy disproven at source; `c7d8e9f0a1b2` `down_revision` correct in code (only a cosmetic docstring nit).

**Merge actions.** See §5.

### 4.12 ci-tooling-docs — **SPLIT** (conf. 93, additive)
**Rationale.** **(A) APPLY (net-new):** `azure-acr-build.yaml`, `.mcp.json`, `migration_scripts/`, `PRPs/`, and the 6 fork `docs/*.md` have zero upstream presence (`git ls-tree v0.9.6` empty). Upstream's only docs change is `docs/SECURITY.md` (fork never touched). **(B) REWORK (CI-disable retarget):** the fork disabled v0.9.2 workflows via `*.disabled` rename, but upstream 0.9.6 RESTRUCTURED the workflow set — DELETED `build-release.yml`, `docker-build.yaml`, `format-backend.yaml`, `format-build-frontend.yaml`, `integration-test.disabled`; ADDED `backend.yaml`, `docker.yaml`, `frontend.yaml`, `release.yml` (kept `release-pypi.yml`). So 4 of 5 fork-disabled files are now orphans, and upstream's NEW active workflows will run CI on the fork unless retargeted.

**Adversarial verify.** AGREE — SPLIT correct; `migration_scripts/` is a standalone SQLite->Postgres utility, NOT Alembic.

**Merge actions.**
- Keep PART A files verbatim; take theirs for `docs/SECURITY.md`.
- PART B: `git mv` each upstream-active workflow (`backend.yaml`, `docker.yaml`, `frontend.yaml`, `release.yml`, `release-pypi.yml`) to `*.disabled`.
- Delete the orphan stale `*.disabled` copies (`build-release.yml.disabled`, `docker-build.yaml.disabled`, `format-backend.yaml.disabled`, `format-build-frontend.yaml.disabled`); re-derive `release-pypi.yml.disabled` from upstream's active file.
- Record the retargeting in FORK_CHANGES.md; verify no upstream workflow is enabled (`gh workflow list`).

---

## 5. Alembic Plan

**Divergence point:** `56359461a091` (add_calendar_tables) — the last migration shared by v0.9.2, v0.9.6, AND the fork.

- **v0.9.2 head:** `56359461a091`.
- **Upstream v0.9.6 single head:** `461111b60977` (add missing PKs to legacy peewee tables). Chain: `56359461a091 -> 4de81c2a3af1 (pinned_note) -> a0b1c2d3e4f5 (ix_memory_user_id) -> 3c9b0ca343fd (knowledge_directory) -> 461111b60977`.
- **Fork head:** `a2b3c4d5e6f7`. Chain: `56359461a091 -> a8f52d3c1e7b (processing_task) -> c7d8e9f0a1b2 (repair) -> d8e9f0a1b2c3 (normalize) -> f0a1b2c3d4e5 (backfill tables) -> f1b2c3d4e5f6 (backfill cols) -> a2b3c4d5e6f7 (backfill processing metadata)`.

**After merge -> TWO heads** (`461111b60977` + `a2b3c4d5e6f7`).

**Resolution (per `docs/ALEMBIC_MERGE_PLAYBOOK.md`):**
```
alembic merge heads -m "merge upstream v0.9.6 + fork recovery chain"
# -> new merge revision, down_revision = ('461111b60977','a2b3c4d5e6f7')
```
- Do **NOT** re-parent the fork chain or rewrite revision IDs. Do **NOT** add new repair/backfill migrations during the merge.
- Verify single head post-merge: `alembic heads`.

**Same-node body conflict (separate from the two-head case):** `f1e2d3c4b5a6_add_access_grant_table.py` has the SAME revision + `down_revision` (`8452d01d26d7`) in all three refs. Resolve the `upgrade()` textual conflict by keeping the fork body and folding in upstream's `insp.clear_cache()` (§4.7). This node sits below the divergence and is unaffected by `merge heads`.

**Redundancy / collision:**
- No fork migration is rendered redundant by 0.9.6. All 4 upstream migrations are net-new for the fork (disjoint tables).
- The only intersection is `note.is_pinned` (fork re-adds idempotently; upstream drops it after moving data to `pinned_note`). Order so upstream `4de81c2a3af1` runs; the fork re-add then becomes a harmless redundant empty column. Optionally flag in `f1b2c3d4e5f6` for future cleanup.

**Validation:** run `alembic upgrade head` against (a) a fresh SQLite dev DB and (b) a Postgres clone of a drifted prod DB — confirm both upstream-new tables and fork backfills converge without error.

---

## 6. Recommended Merge Order, FORK_CHANGES Regeneration, Pre-merge To-Do

### Pre-merge to-do (BLOCKING)
**`src/lib/components/workspace/Knowledge/KnowledgeBase.svelte` and `.../KnowledgeBase/Files.svelte` are currently UNCOMMITTED (git status `M`).** This is the flicker-fix WIP (commit context `98cff8eb2`). **Commit or stash these before starting the merge** — the per-kb-rag-settings-ui (4.4) REWORK depends on re-applying the flicker fix onto upstream's rewritten `searchKnowledgeFilesById` body, and a dirty tree will obscure the 3-way merge. Decision needed: fold the WIP into the merge plan (preferred) or commit it as a discrete pre-merge change so it shows up cleanly in the conflict resolution.

### Recommended merge order
1. **Migrations first** — merge upstream, then `alembic merge heads`; resolve the `f1e2d3c4b5a6` same-node body conflict (§5, §4.7). Keep all 6 fork recovery files + `a8f52d3c1e7b` (processing) intact.
2. **config.py / env.py** (4.10) — rewrite fork fields to `ConfigVar`, fix the two ONEDRIVE/DEFAULT_RAG_TEMPLATE gotchas. Everything downstream imports these.
3. **db.py + schema-validation + processing model** (4.9 + 4.5) — merge together (validation imports `ProcessingTask`); JSONField REWORK; append validation block; wire `main.py` lifespan + router.
4. **retrieval/utils.py** (4.2) — take upstream as base, re-inject fork defs, hand-merge security guards into `get_sources_from_items`. Re-apply `ProcessingTaskTracker` here (cross-group dep for 4.5's cancel/retry).
5. **middleware.py + task.py** (4.3) — re-graft force-retrieval gates onto `allowed_files`; make `rag_template` async-compatible.
6. **tools.py + mcp/client.py** (4.8) — clean injections.
7. **routers/knowledge.py + models/knowledge.py + graph_client + SharePoint files** (4.1) — re-inject SharePoint block; re-add `meta` field.
8. **Frontend KB UI** (4.4) — reshape the fork overlay onto upstream's redesigned `KnowledgeBase.svelte`; dedupe `AdjustmentsHorizontal`; re-apply flicker fix; hand-merge `AddContentMenu`. Re-add `RagSettingsModal`, Documents.svelte toggle, i18n.
9. **CI/docs** (4.12) — net-new files verbatim; retarget workflow `*.disabled`.
10. **Validation gate** — `pytest backend/open_webui/test/{retrieval,sharepoint,processing}/`, `npm run lint`, `npm run build`, backend startup smoke (schema-validation log line + JSONField round-trip).

### FORK_CHANGES.md regeneration
After merge, regenerate `docs/FORK_CHANGES.md` to fix the inventory drift surfaced by this triage:
- **Remove the phantom pseudonymizer entries** (lines 116, 123, the `|pseudonymizer` detector token on line 136) — keep the genuine `ProcessingTaskTracker`/`process_file` note (4.6).
- **Reclassify access-grant-sharing** — note the ACL system is upstream-legacy; the only fork artifact is the `f1e2d3c4b5a6` idempotency rewrite; tools.py/knowledge.py entries are misattributed to the schema-fix and SharePoint groups (4.7).
- **Correct the db.py attribution** — `get_async_db_context`/async engine/SSL/SelectorEventLoop are upstream-legacy, not fork-new; the real fork delta is JSONField guards + the validation block (4.9).
- **Record the workflow-disable retargeting** (which 0.9.6 workflows are now `.disabled`) so the next upstream bump re-applies cleanly (4.12).
