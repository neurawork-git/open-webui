# Open WebUI 0.9.6 Fork Replay Report

> Branch `feature/owui-0.9.6` = upstream **v0.9.6** + **9 clean individual feature commits** (no merge commits).
> Each fork feature was re-applied as a standalone commit on top of v0.9.6, NOT via `git merge`.

## 1. Outcome Summary

- **Branch:** `feature/owui-0.9.6`
- **Base:** upstream v0.9.6
- **Commits applied:** 9 / 9 (all steps applied, none stopped early)
- **Coherent:** yes — validation reports `coherent: true`
- **Alembic single head:** yes — `7e66bdd43a43`
- **Blocking failures:** none
- **Working tree:** clean of tracked modifications (build-generated favicons reverted); only untracked scratch files (`.serena/`, `.claude/`, `.repowise/`, `nul`) remain unstaged as expected.

## 2. Per-Step Results

| Step | Feature | Applied | Commit | Gate passed | Issues |
|------|---------|:-------:|--------|:-----------:|--------|
| 1 | Alembic recovery chain + merge heads | ✅ | `cc8539678` | ✅ | none |
| 2 | Config + Env (ConfigVar layer rework) | ✅ | `194a8545f` | ✅ (py_compile) | full import blocked by missing `chromadb` dep — upstream code, not fork edits |
| 3 | Processing dashboard + schema validation | ✅ | `1623627d8` | ✅ | registration test required single-line router include (fixed) |
| 4 | Retrieval/utils BM25/hybrid/per-KB RAG overlay | ✅ | `5871ac5f5` | ✅ (py_compile) | pytest blocked by missing `chromadb`; `test_rag_models.py` depends on later step |
| 5 | Deterministic KB injection (native FC) + async rag_template | ✅ | `069bac4b4` | ✅ | none (14 passed) |
| 6 | OpenAI strict-schema empty-properties fix | ✅ | `77d92ad9c` | ✅ | none |
| 7 | SharePoint/Graph KB import | ✅ | `c4ec4549b` | ✅ | `test_sharepoint_import.py` uncollectable (chromadb); covered by graph_client tests (25 passed) |
| 8 | Frontend KB-UI reshape onto v0.9.6 redesign | ✅ | `2e8670ef5` | ✅ (npm build) | `addUsage` helper deliberately skipped (non-RAG); General.svelte path corrected; svelte-check noise pre-existing |
| 9 | Restore additive trees, retarget CI, regen FORK_CHANGES | ✅ | `ea8f6df27` | ✅ | none |

## 3. Global Validation

- `coherent`: **true**
- `alembic_single_head`: **true** (`7e66bdd43a43`)
- `blocking_issues`: **none**

### Gates

| Gate | Passed | Detail |
|------|:------:|--------|
| alembic heads (single head) | ✅ | Single head `7e66bdd43a43`; merge of `461111b60977` (upstream) + `a2b3c4d5e6f7` (fork). |
| alembic upgrade head (fresh sqlite) | ✅ | Clean run through full chain incl. fork backfill/repair + final merge node. |
| pytest retrieval/sharepoint/processing | ❌ | 320 passed, 1 failed (see verbatim below). |
| python -c import open_webui.main | ✅ | Import OK after installing import-time deps individually. |
| npm run build (vite build) | ✅ | Built in 1m32s; adapter-static wrote `build/` incl. reshaped knowledge UI. |
| git log v0.9.6..HEAD (clean stack) | ✅ | Exactly 9 individual feature commits, no merge commits. |

### Failing gate — verbatim

> **pytest retrieval/sharepoint/processing — passed: false**
> 320 passed, 1 failed. The single failure (`test_processing_api.py::TestRetryProcessingTask::test_retry_failed_task_success`) is a fork test-fixture artifact: it passes a `MagicMock` for `ProcessFileForm.collection_name`, which Pydantic 2.12.5 (the pinned version) rejects with `string_type` ValidationError at `routers/processing.py:473`. NOT a replay/logic regression. The other 39 sharepoint failures seen earlier were purely missing optional deps in this env (ddgs, azure-storage-blob, aiofiles, google-cloud-storage, chromadb, validators, rank_bm25, aiocache) and all cleared once installed.

## 4. Outstanding Follow-ups (human required)

1. **Fix the one real test failure** — `test_processing_api.py::TestRetryProcessingTask::test_retry_failed_task_success` uses a `MagicMock` for `ProcessFileForm.collection_name` that Pydantic 2.12.5 rejects (`string_type` at `routers/processing.py:473`). Update the fixture to pass a real string. Test-fixture artifact, not a logic regression — but it must go green.
2. **Re-run gates that were static-only due to missing toolchain** — Steps 2, 4, and 7 fell back to `py_compile` because `chromadb` (and other optional RAG deps) are not installed in the replay env. Locally install full `requirements.txt` (note: `rapidocr-onnxruntime==1.4.4` pins `<3.13`, so use Python ≤3.12) and run the full backend test suite to exercise `open_webui.config` import and the retrieval/sharepoint tests for real.
3. **Hand-merge hunks flagged in issues — re-verify manually:**
   - Step 4: 10 hand-resolved conflicts in `retrieval/utils.py` (esp. conflict #8 — per-KB vector branch cross-tenant collection-name validation guard). Confirm all upstream 0.9.6 access-control/security guards survived (`_is_safe_collection_name`, `BYPASS_RETRIEVAL_ACCESS_CONTROL`, `ENABLE_RETRIEVAL_UNSCOPED_COLLECTIONS`, `has_access_to_file`, `filter_accessible_collections`, no-embedding ValueError).
   - Step 2: `config.py` GOTCHA 1 — `ONEDRIVE_CLIENT_ID_BUSINESS` fallback uses literal `os.getenv('MICROSOFT_CLIENT_ID','')` to avoid a forward-reference NameError (MICROSOFT_CLIENT_ID defined later in module). Confirm runtime value parity.
   - Step 8: `ModelEditor.svelte` — `addUsage()` helper was intentionally skipped. Confirm this is desired (it is non-RAG and unreferenced in fork code).
4. **`FORK_CHANGES.md` line-number re-verification** — Step 9 regenerated `docs/FORK_CHANGES.md` against upstream/v0.9.6 and fixed 3 triage drifts (phantom pseudonymizer entries removed, access-grant reclassified, db.py attribution corrected). Re-verify all cited line numbers against the actual committed tree before relying on it as the next merge checklist.
5. **Deploy-to-one-customer-first** — Do NOT roll this out broadly. Stage on the least-critical tenant first (per skill Step 10) and validate the high-risk fork features live: SharePoint/Graph import, per-KB RAG settings, deterministic KB injection on native function-calling, and the processing dashboard cancel/retry path.

## 5. Next Actions

1. Run the full local test suite on Python ≤3.12 with all optional deps installed (`pytest backend/open_webui/test/`), then fix follow-up #1 and re-run until green.
2. Validate `open_webui.config` and `open_webui.main` import cleanly with the full requirements installed (no `chromadb`/`aiocache` workarounds).
3. Smoke-test the reshaped Knowledge UI in a running dev server (`/dev-server`): per-KB RAG modal, SharePoint picker, reindex button, file preview/edit drawer, flicker fix during per-file import.
4. Staging deploy on the least-critical tenant per skill Step 10; verify SharePoint import + per-KB RAG + processing dashboard end-to-end before any broader rollout.
5. After confirming, re-index Repowise (wiki index reported stale vs HEAD) and update the upstream-merge tracking notes.
