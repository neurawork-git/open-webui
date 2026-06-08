# Playwright Deploy-Smoke-Protokoll (Fork)

> Reproduzierbares Verifikations-Protokoll nach jedem Deploy der `neurawork`-Fork
> (z. B. Upstream-Merge `0.9.x`, RAG-Overlay-Änderung, SharePoint-KB-Fix).
> Kombiniert **Cluster-/Migrations-Gate** (kubectl) + **Live-Browser-Funktionstest**
> (`playwright-live` Extension, echte eingeloggte Session als Maximilian König).
>
> Warum dieses Dokument: Es gibt **kein** Cypress/E2E-Specset für diese Fork
> (`cypress/` ist leer). `run-tests` deckt nur Unit/Component (vitest + pytest) ab.
> Dieses Protokoll ist der manuelle/halb-automatisierte Smoke-Layer darüber.

---

## 0. Wann anwenden

- Nach Deploy eines neuen Image-Tags auf einen OWUI-Pod in `thecluster`
  (`n8n/n8n-stack-openwebui` = intern `openwebui.neurawork.app`,
  `open-webui-test/...-webui` = `openwebui-test.neurawork.app`).
- Nach jedem Upstream-Merge (`alembic-merge`-Skill) — dann ist Schritt **B (Migrations-Gate)** Pflicht.
- Vor dem Promoten eines Feature-Tags auf `latest`/`main`.

Pass-Kriterium gesamt: **alle MUSS-Checks grün, 0 console errors auf jeder Route, Migrations-Kette ohne Error auf Single-Head.**

---

## A. Pre-Flight (Cluster-Zustand, read-only)

```bash
CTX=thecluster; NS=n8n; DEP=n8n-stack-openwebui   # ggf. open-webui-test / ...-webui anpassen
POD=$(kubectl --context $CTX -n $NS get pods -l '' -o name | grep openwebui | head -1)

# 1. Image-Tag = erwarteter Build?
kubectl --context $CTX -n $NS get deploy $DEP \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
# MUSS: neuraworkacr.azurecr.io/open-webui:git-<HEAD-short-sha>

# 2. Rollout fertig + Pod ready, 0 restarts
kubectl --context $CTX -n $NS rollout status deploy/$DEP --timeout=180s
kubectl --context $CTX -n $NS get pods | grep openwebui
```

> **Gotcha:** `rollout status` kann mit `timed out waiting for the condition` fehlschlagen,
> obwohl der Deploy ok ist — die Alembic-Migration läuft **vor** dem Readiness-Probe-Fenster
> und kann es überschreiten. Dann erneut `rollout status` aufrufen → wird grün.
> Niemals allein aus dem Timeout auf Fehlschlag schließen; immer Pod-`ready` + Log prüfen.

---

## B. Migrations-Gate (MUSS bei Upstream-Merge) — **vollen** Log prüfen, nicht nur `--tail`

```bash
# Alle Migrations-Zeilen des Boots
kubectl --context $CTX -n $NS logs $POD | \
  grep -iE 'running migrations|context impl|will assume|running upgrade'

# Errors/Tracebacks (MUSS leer bzgl. Migration sein)
kubectl --context $CTX -n $NS logs $POD | \
  grep -iE 'error|traceback|exception|sqlalchemy.exc|does not exist|could not|alembic.*FAIL'
```

Pass-Kriterien:
- [ ] `Context impl PostgresqlImpl.` + `Will assume transactional DDL.`
- [ ] Upgrade-Kette endet auf dem **Single-Head** der Fork
      (aktuell `7e66bdd43a43` = *merge upstream v0.9.6 + fork recovery chain*).
      Single-Head lokal verifizieren: parse `backend/open_webui/migrations/versions/*.py`
      → genau **1** revision ohne ist-down_revision (siehe `alembic-merge`-Skill).
- [ ] Keine `sqlalchemy.exc` / `relation does not exist` / Traceback **in der Migrationsphase**.
- [ ] **Bekannt-benign, KEIN Blocker:**
      `socket.main:periodic_session_pool_cleanup - Unable to renew session cleanup lock. Exiting.`
      → Redis-Session-Lock-Layer (Session-Sharing), nicht die DB-Migration.

Backend-Gesundheit (von der Workstation gegen die Ingress-URL):
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://openwebui.neurawork.app/health      # 200
curl -s https://openwebui.neurawork.app/api/version                                  # {"version":"0.9.6",...}
curl -s https://openwebui.neurawork.app/api/config | python -m json.tool | head      # features-Keys vorhanden
```

---

## C. Live-Browser-Setup (`playwright-live`, echte Session)

1. User hat Chrome offen + Extension „Playwright extension" im neurawork-Profil installiert.
2. Erster `mcp__playwright-live__browser_*`-Call → Tab-Picker/Connect-Seite → User wählt Tab
   (`✅ "..." connected.` im Snapshot).
3. **Niemals** den headless-Server `playwright`/`plugin:playwright` für diesen Test nehmen —
   der landet auf der `/auth`-Login-Wall (frisches Profil, keine Session).
4. Bedienmodell: `browser_snapshot` → `[ref=eXX]` → Action mit `target=<ref>`. Pro Schritt frischer Snapshot.

```text
mcp__playwright-live__browser_navigate  url=https://openwebui.neurawork.app
mcp__playwright-live__browser_snapshot
```
Pass: URL bleibt `/` (kein Redirect auf `/auth`), Benutzermenü zeigt **Maximilian König**.

---

## D. Workflow-Matrix (Live-Funktionstest)

Pro Workflow: navigieren → snapshot → interagieren → erwartetes Ergebnis + `browser_console_messages level=error` == leer.

| # | Workflow | Route / Aktion | Erwartetes Ergebnis | MUSS |
|---|----------|----------------|---------------------|------|
| D1 | **Auth / Session** | `/` | Chat-UI, kein `/auth`-Redirect, Username korrekt | ✅ |
| D2 | **Chat-Inferenz (E2E)** | Modell wählen, Prompt senden (`"Antworte nur mit: DEPLOY-OK"`) | Assistant streamt Antwort, URL → `/c/<uuid>` (persistiert), Auto-Titel generiert | ✅ |
| D3 | **Modell-Liste** | Modell-Selector öffnen (`Ausgewähltes Modell: …`) | Modelle laden (Ollama/OpenAI/Connections), keine leere Liste | ✅ |
| D4 | **Workspace / Knowledge** | `/workspace/knowledge` | KB-Liste rendert (Fork-KB-UI auf v0.9.6-Redesign) | ✅ |
| D5 | **KB öffnen + Inhalt** | eine KB öffnen → `KnowledgeBase.svelte` | Dateien/Chunks sichtbar, `AddContentMenu` öffnet | ✅ |
| D6 | **SharePoint/Graph-Import** (Fork) | KB → Add Content → SharePoint → `SharePointPicker.svelte` | Picker lädt (Graph-OAuth), Site/Ordner-Navigation erscheint (oder klarer Auth-Prompt) | ✅ |
| D7 | **RAG-Retrieval im Chat** | Chat mit `#<KB>` referenzieren, fragen | Zitate/Quellen erscheinen, Antwort nutzt KB-Inhalt (BM25/Hybrid-Overlay) | ✅ |
| D8 | **Per-KB / Per-Level RAG-Settings** (Fork) | KB-Settings bzw. `RagSettingsModal` | Hybrid/BM25/Top-K-Felder editierbar, Save persistiert | ⬜ |
| D9 | **Admin → Document-Processing-Dashboard** (Fork) | `/admin/processing` → `Processing.svelte` | Dashboard rendert, Job-/Schema-Validierungs-Status sichtbar | ⬜ |
| D10 | **Admin → Settings/Documents** | `/admin/settings` → Documents | RAG-Engine/Embedding-Config lädt, Werte = erwartete Prod-Config | ⬜ |
| D11 | **File-Upload** | Chat → Datei anhängen | Upload → Verarbeitung → im Kontext nutzbar | ⬜ |
| D12 | **Channels** | `/channels/<id>` | Channel lädt, Nachrichten-Historie sichtbar | ⬜ |

✅ = MUSS (Deploy gilt sonst als nicht verifiziert) · ⬜ = SOLL (bei feature-relevantem Deploy hochstufen).

> Test-Hygiene: D2 erzeugt einen echten Chat in der Live-Historie. Kurzen Marker-Prompt nutzen,
> danach optional den Test-Chat löschen. Keine destruktiven Aktionen in Admin/KB ohne User-OK.

---

## E. Abschluss / Reporting

- [ ] Alle MUSS-Checks (B + D1–D7) grün, 0 console errors.
- [ ] Image-Tag im Cluster == erwarteter HEAD-SHA.
- [ ] Ergebnis als kurze Tabelle an den User (Check / Ergebnis), Migrations-Head zitieren.
- Bei rot: Pod-Logs (`kubectl logs $POD`) + betroffene Route-Console an den User, **kein** „sollte
  funktionieren" — Ursache belegen (Hot Rule: Push ≠ Fix).

## Referenzen
- Live-Browser-Setup-Details: `chief-of-staff/brain/reference_playwright_live_browser_control.md`
- Upstream-Merge / Single-Head-Disziplin: `.claude/skills/alembic-merge/SKILL.md`
- Unit/Component-Tests: `.claude/skills/run-tests/SKILL.md`
- Fork-Änderungs-Checkliste: `docs/FORK_CHANGES.md`, `docs/OWUI_0.9.6_REPLAY_REPORT.md`
