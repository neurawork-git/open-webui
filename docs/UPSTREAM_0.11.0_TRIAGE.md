# Upstream v0.11.0 Triage — Fork-Vergleich (Stand 2026-07-27)

> Analyse + Umsetzung am selben Tag. Basis: `feature/owui-0.10.2` (Merge-Stand v0.10.2) gegen Tag `v0.11.0`.
> Ergebnis-Branch: `feature/owui-0.11.0`.
> Verwandt: `docs/UPSTREAM_0.10.2_TRIAGE.md`, `docs/FORK_CHANGES.md`, `docs/ALEMBIC_MERGE_PLAYBOOK.md`.

---

## 1. TL;DR

- **616 Upstream-Commits, 649 Dateien** (v0.10.2 → v0.11.0). Größter Brocken seit 0.9.6.
- **Der Blocker ist diesmal das UI, nicht die Config.** 0.11.0 baut die Oberfläche komplett neu
  (`AdminSettingSection`/`AdminSettingRow`/`AdminSettingField`, `UserSetting*`, `<AccessButton />`).
  Das Config-System aus 0.10.2 bleibt unverändert — kein dritter Config-Rewrite in Folge.
- **8 Konflikte**, davon 1 im Backend (`utils/middleware.py`), 7 im Frontend. `retrieval/utils.py`,
  `routers/knowledge.py`, `routers/retrieval.py`, `main.py`, `config.py`, `utils/tools.py` haben
  sauber automatisch gemerged — der teuerste Overlay des Forks (RAG, 880 Zeilen) war unkritisch.
- **Zwei Fork-Anpassungen schrumpfen**, weil Upstream nachgezogen hat: der Full-Context-Default
  beim Chat-Upload (jetzt `defaultUploadContext`-Setting) und der Spinner-Leak beim KB-Upload
  (Upstream fixte einen der zwei Handler). Alles andere bleibt fork-only.
- **Drei Features aus dem Notfall-Commit vom 2026-07-15 sind nachgezogen** (Processing-Tracker,
  Blank-Query-Fallback, Spinner-Fix) — sie lagen auf `chore/claude-md-lean` und waren nie auf
  `feature/owui-0.10.2`. FORK_CHANGES §6 hatte das als offene Schuld vermerkt.
- **Drei vorbestehende Defekte aufgedeckt** (nicht vom Merge verursacht), siehe §5.

---

## 2. Was 0.11.0 mitbringt (fork-relevanter Ausschnitt)

### 2.1 UI-Rebuild

Betrifft jede Fork-Injection in Settings-Komponenten. Konkret umgestellt:

| Alt | Neu |
|---|---|
| rohe `<div class="mb-2.5 flex w-full justify-between">`-Blöcke | `<AdminSettingRow label description let:labelId>` |
| Textarea-Blöcke mit eigenem Label-`<div>` | `<AdminSettingField label description>` |
| inline Access-Button (`<button>` + `LockClosed`) | `<AccessButton on:click />` |
| Admin-Nav `class="min-w-fit p-1.5 …"` | `class="min-w-fit px-1 text-sm …"` |

`Documents.svelte` und `ModelEditor.svelte` waren so weit umgebaut, dass Hand-Merge sinnlos war —
beide per `--theirs` genommen, Fork-Blöcke im neuen Idiom neu gesetzt (Playbook Step 3).

### 2.2 Sicherheits-Fixes mit Fork-Berührung

- **`folder_knowledge` filtert jetzt gegen den Folder-OWNER**, nicht gegen den Aufrufer:
  `get_owner_accessible_folder_files(folder)` ersetzt `get_accessible_folder_files(folder.data['files'], user)`.
  Das ist der Fix „Files attached to a shared folder". Übernommen; der Fork-Dual-Path
  (Force-Retrieval → RAG-Injection *und* Sidecar) sitzt darüber.
- Diverse ACL-Verschärfungen (Chat-Ownership, Tool-Source, Model-Listing) — additiv, keine Fork-Kollision.

### 2.3 Neue Upstream-Features, die Fork-Anpassungen ersetzen

- **`defaultUploadContext`** (`'full' | 'focused'`, User-Setting, Upstream-Default `'focused'`):
  ersetzt den unbedingten Fork-Override in `MessageInput.svelte`. Der Fork kippt jetzt nur noch
  den ungesetzten Default auf `'full'` — an zwei Stellen, weil `MessageInput` `$settings` direkt
  liest und der Wert erst nach dem ersten Speichern im Store liegt.
- **KnowledgeBase-Upload-Cleanup**: Upstream räumt die optimistische Zeile im Directory-Upload-
  Handler jetzt selbst ab (`item.itemId !== fileItem.itemId`). `uploadFileHandler` hat den Bug
  weiterhin (vergleicht `file.id !== uploadedFile.id`, bei Fehlern `undefined`) → Fork-Patch bleibt,
  aber nur noch für diesen einen Handler.
- **Chroma-`has_collection`** wurde in #27394 nochmals optimiert (gezielte Abfrage statt Listing).
  Der Fork-Eintrag war schon mit 0.10.2 erledigt.

### 2.4 Performance-Umbauten, die den Fork streifen

0.11.0 batcht sehr viele Config-Lookups. In `chat_completion_files_handler` hat Upstream
**dieselbe** `Config.get_many`-Batchung eingeführt, die der Fork dort schon hatte. Nach dem
Merge standen zwei aufeinanderfolgende `get_many`-Aufrufe im Code; der Upstream-Aufruf wurde
entfernt, weil die Fork-Variante eine Obermenge ist (enthält zusätzlich `rag.enable_reranking`).

---

## 3. Fork-Inventar: bleibt / schrumpft / weg

| Fork-Anpassung | Verdikt | Beleg gegen v0.11.0 |
|---|---|---|
| BM25-Tokenizer (`tokenize_for_bm25`, `ScoringBM25Retriever`) | **BLEIBT** | `retrieval/utils.py:524` weiter nacktes `BM25Retriever.from_texts` |
| `RAG_NATIVE_FC_FORCE_RETRIEVAL` | **BLEIBT** | Injection-Gates weiter strikt `== 'legacy'` (middleware.py:2452, :2466); kein Force-Flag upstream |
| `ENABLE_RAG_RERANKING` (An/Aus) | **BLEIBT** | Upstream hat nur `rag.reranking_engine/model/batch_size`, keinen Toggle |
| Per-KB/User/Model-RAG-Settings + `retrieval/models.py` | **BLEIBT** | `grep -l rag_settings` über `backend/` + `src/` in v0.11.0 = 0 Treffer; `retrieval/models.py` existiert upstream nicht |
| Pyodide-Prompt-ConfigVar | **BLEIBT** | `CODE_INTERPRETER_PYODIDE_PROMPT` weiter Konstante (config.py:474), kein Admin-Override |
| `properties: {}`-Fix (tools.py, mcp/client.py) | **BLEIBT** | `clean_properties` (tools.py:905) injiziert es nicht; `mcp/client.py:105` reicht `inputSchema` roh durch |
| `internal/db.py` JSONField-Guard | **BLEIBT** | upstream weiter Einzeiler `json.loads(value)` |
| `utils/task.py` `rag_template`-Erweiterung | **BLEIBT** | Upstream-Signatur jetzt `async def rag_template(template, context, query)`; Fork hängt 4. Parameter mit Default an. **Aber:** kein Aufrufer befüllt ihn → §5.2 |
| SharePoint/Graph-Import, Processing-Dashboard, Fork-Migrationen, Tests | **BLEIBT** (additiv) | kein struktureller Konflikt |
| Chat-Upload Full-Context-Default (~21 Z.) | **SCHRUMPFT** auf 2 Z. | Upstream `defaultUploadContext` (#20900) |
| KnowledgeBase-Spinner-Fix (17 Z.) | **SCHRUMPFT** auf ~8 Z. | Upstream fixte Handler 1 |
| Fork-Favicons in `backend/open_webui/static/` | **WIRKUNGSLOS** | wird bei jedem Import überschrieben → §5.1 |

---

## 4. Alembic

Sieben neue Upstream-Migrationen (`856c5b02fb54` chat_message_meta, `9a1b2c3d4e5f`
current_message_id, `c49178636c78` chat_variables, `b0018471bbbe` user_variables,
`55f1302ac17c` memory-Index, `959eaac8f909` automation_folder_id, `f0bd01a18a3d`
unique_normalized_user_email) — alle auf Upstream-Tabellen, keine berührt `processing_task`.

Standardfall: zwei Heads nach dem Merge, `alembic merge heads` → `ad192b50687b` (kein DDL).

```
pre-merge  : e48721182479 (head)
post-merge : e48721182479, f0bd01a18a3d
merge node : ad192b50687b (mergepoint)
fresh walk : ad192b50687b, processing_task vorhanden, 44 Tabellen
```

---

## 5. Kritische Funde (unabhängig vom Merge)

Alle drei auf `feature/owui-0.10.2` verifiziert vorbestehend.

### 5.1 `backend/open_webui/static/` wird von jedem Backend-Import geleert

`config.py` löscht beim Modul-Import **jede lose Datei** in `STATIC_DIR` und befüllt danach aus
`FRONTEND_BUILD_DIR/static`:

```python
if STATIC_DIR.exists():
    for item in STATIC_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()          # ohne Build danach: Verzeichnis bleibt leer
```

Im Dev-Checkout ohne Frontend-Build bedeutet das: `pytest`, `alembic` oder ein nackter
Backend-Start löschen versionierte Assets (favicons, splash, logo, webmanifest, loader.js,
`user-import.csv`). Ein nachfolgendes `git add -A` committet die Löschung.

**Das ist bereits einmal passiert:** Der Notfall-Commit `39af2051` (2026-07-15) enthält Favicons,
die byte-identisch mit Upstream sind (`v0.10.2` == `v0.11.0` == wip). Das Fork-Branding wurde also
aus einem Build-Output überschrieben — FORK_CHANGES §8 las das als „neues Branding pending" und
lag damit falsch. Beim 0.11.0-Merge wurden die Fork-Favicons deshalb bewusst *nicht* aus dem
wip übernommen.

Folgerung: Der Favicon-Overlay in `backend/open_webui/static/` ist strukturell wirkungslos —
im Container läuft erst der Frontend-Build, dann überschreibt der Backend-Import aus
`build/static/`. Echtes Branding gehört in den Frontend-`static/`-Baum. Der Fork führt dort
aktuell die **Upstream**-Datei (`static/favicon.png` == `v0.11.0`).

**Sofortmaßnahme bei jedem Merge:** nach Backend-Tooling `git status backend/open_webui/static/`
prüfen, bevor gestaged wird.

### 5.2 `{{KNOWLEDGE_BASES}}` wird nie befüllt

`rag_template()` nimmt `knowledge_bases` entgegen und rendert den Platzhalter, aber alle drei
Aufrufstellen in `utils/middleware.py` (Zeilen 860, 866, 5252) rufen dreiargumentig auf. Die
Template-Variable bleibt leer. Bestand schon in 0.10.2 (`git show feature/owui-0.10.2` → kein
Aufrufer mit `knowledge_bases=`). Der Fork sammelt die KB-Metadaten in
`per_knowledge_rag_settings` bereits ein — die Verdrahtung zum Template fehlt.

### 5.3 `onedrive-file-picker.test.ts` ist rot (9 von 13)

Alle Fehler: `window is not defined`. Das Repo deklariert weder `jsdom` noch `happy-dom`, und
`vite.config.ts` setzt keine Test-Environment. Testdatei, getestetes Modul, vitest (1.6.1),
`@azure/msal-browser` (4.5.0) und `vite.config.ts` sind zwischen `feature/owui-0.10.2` und dem
Merge-Ergebnis byte-identisch → kein Zusammenhang mit 0.11.0.

---

## 6. Verifikation

| Prüfung | Ergebnis |
|---|---|
| Alembic-Kette frisch (SQLite) | grün, ein Head `ad192b50687b`, `processing_task` vorhanden |
| Fork-Backend-Tests (`processing`, `retrieval`, `sharepoint`) | **321 passed** — identische Zahl wie beim 0.10.2-Merge |
| Injection-Detektoren (FORK_CHANGES §6) | alle Treffer; kein auskommentierter Fork-Router in `main.py` |
| `npm run check` | 8465 Fehler (Fork) vs 8433 (acht Konfliktdateien auf Upstream zurückgesetzt). Delta +32 = untypisierte Fork-Properties + proportional mehr implizites `any`; **keine neue Fehlerklasse** |
| `npx vitest run` | 4 passed / 9 failed — ausschließlich §5.3, vorbestehend |
| Workflow-Renames | nur `azure-acr-build.yaml` aktiv; neues `issue-label.yaml` auf `.disabled` |

### 6.1 Live-Test auf `neurawork-test` (Tier 2, 2026-07-27)

Im Live-Chrome gegen `https://openwebui-test.neurawork.app` durchgeführt.

| Check | Ergebnis |
|---|---|
| D1-auth | ✅ Entra-SSO durchgelaufen, kein `/auth`-Redirect; UI zeigt Release-Dialog **v0.11.0** |
| D9-processing | ✅ Dashboard rendert (Stat-Kacheln, Status-Filter, Tabelle, Live-Polling) |
| D10-admin-docs | ✅ Fork-Toggle **„Wissensdatenbank-Retrieval bei nativem Tool-Calling erzwingen"** steht ganz oben im Abschnitt „Abruf", Label + Beschreibung im neuen `AdminSettingRow`-Idiom, de-DE-Keys lösen auf |
| Pyodide-Prompt (CodeExecution) | ✅ Feld **„Pyodide Guardrail Prompt"** hinter der Prompt-Vorlage, gegated auf Engine `pyodide` |
| Admin-Nav | ✅ Processing-Tab mit der 0.11.0-Tab-Klasse |
| D5-kb-open | ✅ Button-Reihe wie hand-aufgelöst: **RAG** (Fork) · **Zugriff** (upstream `AccessButton`) · **Neu indizieren** (Fork) |
| D8-rag-settings | ✅ Override-Modal komplett: Top-K, Top-K (Reranker), Relevanzschwelle, BM25-Gewichtung, Hybride Suche, **Reranking**, Full Context, „Reset to Global" |
| D11-upload | ⚠️ Upload + Extraktion + KB-Verknüpfung ok (`status: completed`) — **aber kein Dashboard-Task**, siehe §5.4 |
| D2-chat, D3-models-ui, D7-rag | ⚪ nicht prüfbar: `/api/models` liefert 0 Modelle, die Instanz hat keine LLM-Verbindung |
| D12-channels | ⚪ offen |

Einschränkung des Live-Chrome-Wegs: der Extension-Modus darf keine File-Inputs setzen
(`DOM.setFileInputFiles: Not allowed`). Der Upload lief deshalb per `fetch`/FormData aus dem
Seitenkontext — derselbe Backend-Pfad (`files.py` → `_process_file` → Tracker), aber ohne die
Svelte-Upload-UI. Der Spinner-Cleanup in `uploadFileHandler` ist damit **nicht** live geprüft.

### 5.4 `processing_task`-JSON-Spalten — Dashboard schrieb nichts (gefixt)

Der Upload-Check deckte einen echten Defekt auf: Datei `completed` und an die Collection
gebunden, aber `total_tasks: 0`. Pod-Log:

```
psycopg.errors.DatatypeMismatch: column "error_details" is of type json
but expression is of type character varying
```

`error_details` und `metadata` sind auf Postgres `json` (auf **test und prod** verifiziert),
das Modell deklarierte sie mit dem TEXT-basierten `JSONField` → VARCHAR-Bindung → jedes INSERT
scheitert. Und zwar **still**, weil `_safe_track` Fehler bewusst schluckt: Uploads laufen weiter,
das Dashboard bleibt einfach für immer leer.

Kein Merge-Regress — `models/processing.py` und die anlegende Migration sind byte-identisch zu
`feature/owui-0.10.2`. Der Mismatch lag seit dem 0.9.6-Replay latent, weil die Tracker-Hooks
fehlten und niemand das INSERT auslöste; Prod läuft auf `git-f805abe`, ebenfalls ohne Hooks.
Erst das Wiederherstellen der Hooks in diesem Branch machte ihn erreichbar.

Fix modellseitig auf `sa.JSON` (keine Migration — `json` ist der richtige Typ, die 13
historischen Prod-Zeilen bleiben lesbar), plus Typ-Assertion als Regressionsschutz, da SQLite
beide Typen akzeptiert und die Suite das nie gefangen hätte.

**Nicht geprüft:** Laufzeitverhalten. Kein Deploy, kein Playwright-Smoke. Vor dem Rollout
`docs/PLAYWRIGHT_DEPLOY_SMOKE_PROTOCOL.md` fahren — insbesondere Admin-Settings (UI-Rebuild!),
Processing-Dashboard, SharePoint-Import und KB-RAG-Modal, weil deren Markup neu gesetzt wurde.

---

## 7. Offene Punkte

1. **Release-Branches schneiden**, bevor `feature/owui-0.11.0` nach `main` geht — Stadtbau und
   Falkensteg hängen an Ständen, die der Merge sonst mitzieht (Playbook Step 1, FORK_CHANGES §9).
2. **Staging-Deploy auf genau einem Tenant**, 12 h Soak, erst danach breiter (Playbook Step 10).
   `docs/deploy-test/instances.json` hat dafür eine dedizierte Test-Umgebung.
3. **§5.1 entscheiden:** Fork-Branding in den Frontend-`static/`-Baum verlagern (dann wirkt es)
   oder den toten Overlay in `backend/open_webui/static/` streichen. Aktuell steht er nur da.
4. **§5.2 entscheiden:** `{{KNOWLEDGE_BASES}}` verdrahten oder Platzhalter + Parameter entfernen.
5. **§5.3:** `jsdom` als devDependency + `test.environment` in `vite.config.ts`, sonst ist
   `npm run test:frontend` dauerhaft rot und damit als Signal wertlos.
6. **Sub-Agents / Files-Capability** (neu in 0.11.0) gegen den Fork-Force-Retrieval bewerten:
   Upstream verlagert Attachment-Zugriff zunehmend auf Tool-Calls (`🗂️ Files capability`).
   Ob deterministische Injektion damit langfristig noch der richtige Hebel ist, ist eine
   Produktfrage — für diesen Merge unverändert übernommen.
