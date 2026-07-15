# Upstream v0.10.2 Triage — Fork-Vergleich (Stand 2026-07-14)

> Analyse-Ergebnis VOR dem Merge. Basis: Fork-HEAD (Replay auf `v0.9.6`) vs. Tags `v0.10.0`–`v0.10.2`.
> Vier parallele Recon-Durchgänge: RAG-Architektur upstream, Fork-RAG-Overlays, middleware/KB-inject, restliche Injections.
> Verwandt: `docs/UPSTREAM_0.9.6_TRIAGE.md`, `docs/FORK_CHANGES.md`, `docs/ALEMBIC_MERGE_PLAYBOOK.md`.

---

## 1. TL;DR

- **Blocker Nr. 1 ist nicht RAG, sondern der zweite Config-System-Rewrite in Folge.** v0.10 entfernt die komplette `ConfigVar`/`AppConfig`-Schicht wieder (auf die der Fork bei 0.9.6 gerade migriert ist) und ersetzt sie durch ein per-Key-DB-Model (`models/config.py`, Tabelle `config`, Zugriff `await Config.get('rag.top_k')`). `internal/config.py` existiert in v0.10.2 nicht mehr; `grep ConfigVar` = 0 Treffer (Fork-HEAD: 365).
- **Datenverlust-Risiko:** Die neue Migration `3ff2c63645b8_reshape_config_to_per_key_rows.py` mapped alte Blob-Keys via `BLOB_PATH_TO_KEY` auf per-Key-Rows. Unsere drei Fork-Configs (`RAG_NATIVE_FC_FORCE_RETRIEVAL`, `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE`, SharePoint/Graph-Creds) fehlen in der Map → würden beim Upgrade still verwaisen. Map muss fork-seitig ergänzt werden (eigene Follow-up-Migration, upstream-Datei bleibt unangetastet — Regel 2).
- **Wenig kann ersatzlos weg.** Nur der `folder_knowledge`-Sidecar (upstream nativ), der Chroma-`has_collection`-Fix (upstream gefixt) und zwei stale FORK_CHANGES-Einträge. Per-KB-RAG-Settings, BM25-Tokenization-Fix, Force-Retrieval-Flag, Pyodide-Prompt-ConfigVar, tools.py/MCP-properties-Fix, JSONField-Guard: alles weiterhin fork-only.
- **Kritischer Nebenfund:** Der in FORK_CHANGES.md §6 dokumentierte Chroma-`has_collection`-Fix ist beim 2026-06-REPLAY **verlorengegangen** (HEAD byte-identisch mit v0.9.6). Auf Chroma-Instanzen liefert `has_collection()` damit immer `False`. Prüfen, welche Deploys `VECTOR_DB=chroma` fahren; ggf. Upstream-Fix `15d96b1f2` cherry-picken.

---

## 2. Neue RAG-Architektur in 0.10 (vier Säulen)

### 2.1 Config-Layer: PersistentConfig/ConfigVar → per-Key-DB (`Config.get`)

- Neu: `backend/open_webui/models/config.py` — `config`-Tabelle (`key TEXT PK, value JSON`), Docstring: „Replaces the old single-row JSON blob machinery".
- `config.py` v0.10.2: `DEFAULT_CONFIG`-Registry mit dotted Keys (`'rag.top_k'`, `'rag.enable_hybrid_search'`, …); alte `RAG_*`-Modulvariablen nur noch Seed-Defaults.
- `routers/retrieval.py`: `RETRIEVAL_CONFIG_KEYS`-Map (UPPER_CASE → dotted key), `RetrievalConfig(SimpleNamespace)` mit explizitem `save()`; `save_docs_to_vector_db(config=...)` statt `request.app.state.config`.
- Kein Rename einzelner RAG-Parameter — nur der Zugriffsmechanismus ändert sich. Endpoint-Set von `routers/retrieval.py` ist identisch zu v0.9.6; der 1861-Zeilen-Diff ist ~90 % mechanische Config-Umstellung.
- **Fork-Konsequenz:** Jeder `request.app.state.config.X`- bzw. `ConfigVar`-Zugriff des Forks bricht. Betrifft `retrieval/models.py` (`RAGQuerySettings.from_config`), alle Fork-Endpoints in `routers/knowledge.py`/`routers/retrieval.py`, middleware-Hooks, `main.py`-State-Bindings.

### 2.2 Native DB-Hybrid-Search (aktuell nur pgvector)

- Interface: `VectorDBBase.hybrid_search(...)` (`retrieval/vector/main.py:66`, Default `None` = nicht unterstützt); async via `ASYNC_VECTOR_DB_CLIENT.hybrid_search` + `supports_hybrid_search`-Property.
- Implementiert **nur** in `pgvector.py`: GIN-Index auf `to_tsvector('simple', text)`, Postgres-FTS + Vektor-Suche, Merge per Reciprocal Rank Fusion (`merge_hybrid_search_results`, `rank_constant=60`, gewichtet über `hybrid_bm25_weight`). Deaktiviert bei `PGVECTOR_PGCRYPTO` oder aktiven Metadata-Filtern (→ `None` → Fallback).
- `query_doc_with_hybrid_search` versucht zuerst nativ, fällt bei `None` auf den alten **In-Memory-BM25-Pfad** zurück. In-Memory-BM25 bleibt also für Chroma/Qdrant/Milvus/ES/OpenSearch der einzige Hybrid-Pfad.
- Signatur-Änderung: `query_doc_with_hybrid_search(..., native_hybrid_search: bool = True)` — muss ins Fork-Overlay übernommen werden, sonst bricht der Fallback-Call.

### 2.3 External Knowledge Bases (neuer, paralleler Retrieval-Pfad)

- Neu: `retrieval/external.py` (378 Z.). Provider: externe `qdrant`/`milvus`/`pgvector`-Instanzen; Feld-Mapping konfigurierbar; Identifier-Whitelisting gegen SQL-Injection.
- KB-Markierung: `knowledge.meta = {'source': 'external', 'read_only': True, 'external': {...}}`; External-KBs sind read-only (kein Upload/Embed).
- Einhängung: `get_sources_from_items` (retrieval/utils.py) zweigt bei `meta.source == 'external'` auf `retrieve_external_knowledge(...)` ab — komplett an der lokalen Vector-DB vorbei.
- Neue Endpoint-Gruppe `/knowledge/external/*` in `routers/knowledge.py` (~Zeile 176–900) — kollidiert räumlich mit unserem SharePoint-Import-Overlay.
- **Strategische Note:** Für Company-RAG-Setups (externer RAG-Stack) ist das ein potenzieller upstream-nativer Anschlusspunkt statt Eigenbau — Retrieval-only, read-only.

### 2.4 Agentische Knowledge-Tools + native-FC-Verhalten

- `tools.py` v0.10.2 registriert erweitertes Tool-Set: `list_knowledge_bases`, `search_knowledge_files`, `grep_knowledge_files`, `query_knowledge_files`, `kb_exec`; Knowledge-File-Reads paginiert/gedeckelt (Commit `a285a390c1`).
- `folder_knowledge`-Sidecar ist upstream nativ: `tools.py:518-520` merged `metadata['folder_knowledge']` in `model_knowledge` — exakt unser Fork-Mechanismus, generalisiert.
- Injektion in `form_data['files']` bleibt strikt an `function_calling == 'legacy'` gekoppelt (middleware.py:2363, :2377). **Kein** Force-/Deterministik-Flag upstream — bei native FC verlässt sich 0.10 vollständig auf Tool-Aufrufe des Modells. Unsere Lücke besteht unverändert.
- Achtung: Gate-Vergleich jetzt `== 'legacy'` (Fork: `!= 'native'`) — es gibt offenbar einen dritten `function_calling`-Wert; vor dem Port klären.

---

## 3. Fork-Inventar: weg / schrumpft / bleibt / kollidiert

| Fork-Anpassung | Verdikt | Begründung / Beleg |
|---|---|---|
| `folder_knowledge`-Sidecar (Teil von KB-deterministic-inject) | **WEG** | Upstream nativ (`tools.py:518-520` in v0.10.2). |
| Chroma `has_collection`-Fix (FORK_CHANGES §6) | **WEG** (Eintrag) | Upstream-Fix `15d96b1f2` in 0.10.2. Fork-Code hat den Fix ohnehin nicht mehr (Replay-Verlust, s. §4.1). |
| `ddgs`-Pin in requirements.txt (FORK_CHANGES §6) | **WEG** (Eintrag stale) | `git diff v0.9.6..HEAD -- backend/requirements.txt` leer; upstream bumpte ddgs selbst auf 9.14.4. |
| `RAG_NATIVE_FC_FORCE_RETRIEVAL` (deterministische Injektion bei native FC) | **BLEIBT** (schrumpft) | Lücke upstream unverändert; Sidecar-Hälfte entfällt, Flag + zwei Injection-Sites müssen aufs neue Config-System portiert werden. Injection-Sites strukturell erhalten (v0.10.2 middleware.py:2354-2413). |
| Per-KB-RAG-Settings (`retrieval/models.py`, knowledge.py-Endpoints, RagSettingsModal.svelte) | **BLEIBT** | Kein Upstream-Äquivalent: kein `rag_config` pro KB, alle RAG-Parameter global. `retrieval/models.py` existiert upstream nicht. Port erfordert Umstellung `from_config` auf `Config.get`. |
| BM25-Tokenization-Fix (`tokenize_for_bm25`) | **BLEIBT** | v0.10.2 nutzt weiter nacktes `BM25Retriever.from_texts` ohne Custom-Tokenizer. |
| In-Memory-Hybrid-Search-Overlay (retrieval/utils.py, 2008 Z.) | **KOLLIDIERT (d)** | Muss auf neue Struktur rebased werden: native-hybrid-Pfad + `native_hybrid_search`-Parameter + async-Config-Umbau + External-KB-Zweig in `get_sources_from_items`. Bei pgvector-Deploys zusätzlich Architektur-Entscheidung: nativ vs. Fork-Hybrid (s. §5 offene Fragen). |
| SharePoint-Import + RAG-Settings-Endpoints (`routers/knowledge.py`, 649 Z.) | **KOLLIDIERT (d)** | Upstream-Diff dort 820 Z. (External-KBs + Events + async Config). Hand-Merge, hoher Aufwand. |
| `CODE_INTERPRETER_PYODIDE_PROMPT_TEMPLATE` ConfigVar | **BLEIBT** | Upstream-Konstante existiert weiter (config.py:474), Append-Sites strukturell identisch (middleware.py:2469-2498), aber kein Admin-Override. Neu registrieren im per-Key-System. |
| tools.py + mcp/client.py `properties: {}`-Fix | **BLEIBT** | v0.10.2 `clean_openai_tool_schema` + `list_tool_specs` unverändert ohne Fix. 1:1 re-apply. |
| `internal/db.py` JSONField dict/list-Guard | **BLEIBT** | v0.10.2 weiterhin Einzeiler `json.loads(...)`. Trivial re-apply. |
| `env.py` Fork-Vars (FORK_VERSION_SUFFIX, EMBEDDING_RETRY_*, GRAPH_*, SHAREPOINT_*) | **BLEIBT** | Namensraum disjunkt zu v0.10.2, paste-as-is. |
| `main.py` processing-Router-Injection | **BLEIBT** | `include_router`-Pattern erhalten (v0.10.2 main.py:740). Merge-Rauschen durch entfallene Config-Imports. |
| `utils/task.py` `rag_template`-Erweiterung | **BLEIBT** | `rag_template` upstream byte-identisch zu v0.9.6; upstream ändert andere Funktionen. Sauberer 3-Way-Merge. |
| Processing-Dashboard, Graph-Client, Fork-Migrationen, Tests | **BLEIBT** (additiv) | Kein struktureller Konflikt; Migrationskette: 4 neue + 2 geänderte upstream-Migrationen, keine berührt Fork-Tabellen. Standard `alembic merge heads`. |

---

## 4. Kritische Funde (unabhängig vom Merge)

### 4.1 Chroma `has_collection` — Fix beim Replay verloren

`git diff v0.9.6 HEAD -- backend/open_webui/retrieval/vector/dbs/chroma.py` ist **leer**; FORK_CHANGES.md §6 behauptet aber einen 4-Zeilen-Fix. HEAD enthält den v0.9.6-Bug:

```python
collection_names = self.client.list_collections()   # liefert Collection-Objekte (chromadb 1.x)
return collection_name in collection_names          # immer False
```

Upstream-Fix in 0.10.2: Commit `15d96b1f2` (#25780). Auswirkung auf Chroma-Deploys: `has_collection()` immer `False` → betrifft Reindex-/Delete-Gates. **Sofort prüfen, welche Instanzen `VECTOR_DB=chroma` fahren**; ggf. `15d96b1f2` cherry-picken (nicht neu erfinden).

### 4.2 `BLOB_PATH_TO_KEY` — stiller Config-Verlust beim Upgrade

`3ff2c63645b8_reshape_config_to_per_key_rows.py` migriert nur upstream-bekannte Keys. Fork-Configs, die Admins per API/UI persistiert haben (Force-Retrieval-Toggle, Pyodide-Prompt, SharePoint-Creds), verwaisen beim Reshape. Fix: eigene Fork-Follow-up-Migration, die die drei Key-Pfade nachmigriert (upstream-Migrationsdatei nicht anfassen — Playbook-Regel 2).

### 4.3 FORK_CHANGES.md-Drift

Zwei Einträge nachweislich stale (chroma.py-Diff, ddgs-Pin) — beide behaupten Fork-Diffs, die im HEAD nicht existieren. Detector-Schwäche: `git diff upstream/main..HEAD` prüft gegen den falschen Ref. Bei der nächsten Regeneration Detectors auf `git diff v0.9.6..HEAD` umstellen.

---

## 5. Empfohlene Merge-Reihenfolge + offene Fragen

Reihenfolge (jeder Schritt einzeln verifizierbar):

1. **Chroma-Hotfix separat vorab** (falls Chroma produktiv): cherry-pick `15d96b1f2` auf aktuellen Stand, unabhängig vom 0.10-Merge.
2. **Config-Port als eigenes Mini-PRP**: neues per-Key-Muster verstehen (`models/config.py` vollständig lesen), die 3 Fork-Configs als dotted Keys registrieren, Fork-Follow-up-Migration für `BLOB_PATH_TO_KEY`-Lücke. Vorher klären: dritter `function_calling`-Wert.
3. **Standard-Merge nach Playbook** (`git merge v0.10.2`): Additive unberührt, Injections re-apply (tools.py, mcp/client.py, db.py, env.py, main.py, task.py sind Standard).
4. **RAG-Overlays rebasen**: `retrieval/utils.py` (Signatur + async Config + External-KB-Zweig respektieren), `routers/knowledge.py` (Hand-Merge gegen External-KB-Block), per-KB-Settings auf `Config.get` umstellen.
5. **KB-deterministic-inject schrumpfen**: Sidecar-Code droppen (upstream nativ), nur Flag + zwei Injection-Sites portieren, Gate-Logik an `== 'legacy'`-Semantik anpassen.
6. FORK_CHANGES.md regenerieren (Pflicht, Playbook Step 8) — dabei stale Einträge (§4.3) korrigieren.

Offene Fragen vor Schritt 3:

- **Welche Vector-DB pro Kunden-Deploy?** (chroma vs. pgvector — entscheidet über Dringlichkeit §4.1 und über native-Hybrid-Strategie §2.2). Prüfen in `falkensteg-k8s`/`stadtbau-k8s` values.
- **Dritter `function_calling`-Wert** in v0.10.2 (neben `legacy`/`native`) — Semantik klären, bevor das Force-Flag-Gate portiert wird.
- **External KBs als Ersatz für Teile des Company-RAG-Eigenbaus?** Read-only-Retrieval gegen externe qdrant/milvus/pgvector — bewerten, ob das für Falkensteg-Company-RAG den Eigenanschluss ersetzt.
