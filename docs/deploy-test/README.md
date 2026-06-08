# OWUI Fork — Deploy-&-Test-Workflow

Wiederverwendbarer, kostenbewusster Workflow um einen Fork-Build auf **jede** OWUI-Instanz
zu deployen und zu verifizieren. Kernidee: **getierte Checks** (gratis → teuer) plus
**smartes State-Tracking**, das grüne Frontend-Checks pro Image-Tag/Surface überspringt —
denn Live-Browser-Tests (Tier 2) sind teuer.

> Ersetzt das ältere `docs/PLAYWRIGHT_DEPLOY_SMOKE_PROTOCOL.md` (bleibt als Prosa-Referenz).
> Dieses Verzeichnis ist die ausführbare Version davon.

## Dateien

| Datei | Zweck |
|-------|-------|
| `instances.json` | Instanz-Registry (URL, kube-context/ns/deployment/container, erwartete Feature-Flags) |
| `checks.json` | Check-Katalog mit `tier` + `surface` (Code-Bereiche) + `gate_features` |
| `deploy-test.sh` | Orchestrator: `preflight` (Tier-0-Automatik), `plan`, `report`, `migration-log`, `record` |
| `lib/state.py` | State + Report-Engine (`state.json`) |
| `state.json` | Smart-Memory: pro (Instanz, Check) letztes Ergebnis + verifizierter Tag/Commit |
| `reports/` | Pro Release ein Markdown-Report — was probiert wurde, mit Ergebnis |

## Tier-Modell (warum)

| Tier | Kosten | Was | Wann |
|------|--------|-----|------|
| **0** | gratis | kubectl (Image/Rollout/Migration-Log) + curl (`/health`,`/api/version`,`/api/config`) | **immer**, vollautomatisch |
| **1** | billig | authentifizierte API-Probes (`/api/models`, `/api/v1/knowledge`) — Token nötig | optional, wenn Token da |
| **2** | **teuer** | Live-Browser-Matrix `D1–D12` via `playwright-live` (echte Session, Agent-getrieben) | nur Checks die geändert/nie-grün sind |

Tier 0 fängt ~80 % der Deploy-Fehler ab (Pod crash, Migration-Fail, falscher Tag, Config-Drift)
**ohne** einen Browser zu starten. Tier 2 nur für das, was Tier 0 nicht sehen kann (echtes UI-Rendering,
RAG-Zitate, Mensch-Klick-Pfade).

## Smartes Skippen (`plan`)

`state.json` merkt pro Check: letztes Ergebnis + Tag + Commit. `deploy-test.sh plan` entscheidet je Tier-2-Check:

- **RUN** wenn: noch nie grün **ODER** eine geänderte Datei trifft die `surface[]` des Checks.
- **SKIP** wenn: zuletzt `pass` **und** keine geänderte Datei in der Surface (→ „grün @ git-xxxx, Surface unverändert").
- **N/A** wenn: `gate_features` nicht erfüllt (z. B. SharePoint ohne `enable_onedrive_*` → nicht testbar, kein Fehler).

Geänderte Dateien = `git diff --name-only <base-commit>..<commit>`. `--base-commit` = der Commit des letzten grünen Laufs.
Ohne base-commit → konservativ **alles** laufen lassen. Surface-Treffer = Präfix-Match (`backend/open_webui/retrieval/` trifft alles darunter).

## Ablauf (Standard-Release)

```bash
cd docs/deploy-test
SHA=$(git rev-parse --short=7 HEAD)        # -> Image-Tag git-$SHA

# 1) Build: Branch nach neurawork pushen (CI azure-acr-build -> neuraworkacr.azurecr.io/open-webui:git-$SHA)
git push neurawork "$(git branch --show-current)"
gh run watch <run-id> --repo neurawork-git/open-webui --exit-status    # NICHT durch '| tail' pipen (maskiert exit!)

# 2) Erst auf TEST deployen
kubectl --context thecluster -n open-webui-test set image \
  deploy/open-webui-open-webui-stack-webui open-webui=neuraworkacr.azurecr.io/open-webui:git-$SHA

# 3) Tier 0 (gratis, automatisch)
./deploy-test.sh preflight neurawork-test --expect-version 0.9.6 --expect-tag git-$SHA

# 4) Plan: welche teuren Browser-Checks nötig?
./deploy-test.sh plan neurawork-test --tag git-$SHA --base-commit <letzter-gruener-commit> --commit $(git rev-parse HEAD) \
  --features enable_onedrive_integration=false,enable_onedrive_business=false

# 5) Tier 2 nur für die RUN-Checks (Agent, playwright-live) -> je Check zurückmelden:
./deploy-test.sh record neurawork-test D7-rag pass --tag git-$SHA --note "3 Quellen, Zitat 01-...md"

# 6) Report
./deploy-test.sh report neurawork-test --tag git-$SHA      # -> reports/neurawork-test-git-$SHA-<date>.md

# 7) Erst nach grün: prod (neurawork-prod) — Schritte 2–6 mit ns n8n / deploy n8n-stack-openwebui / container openwebui
```

## Tier-2-Live-Browser — Bedienung (hart erkämpfte Regeln)

1. **`playwright-live`** (Extension), **nicht** der headless `playwright`-Server → sonst frisches Profil = `/auth`-Login-Wall.
2. Neuer MCP-Server greift erst nach **`/restart`** bzw. `/mcp`-reconnect (Tool-Registry wird beim Session-Start fixiert).
3. Erster `browser_*`-Call → Tab-Picker im echten Chrome; User wählt Tab (`✅ connected`).
4. **Refs (`[ref=eXX]`) ändern sich pro Snapshot** → vor jeder Action frisch snapshotten, nie Refs cachen.
5. **`#`-KB-Mention & `@`-Mentions brauchen echte Keystrokes** (`browser_type slowly:true`), `fill` umgeht die Input-Handler → Dropdown öffnet nicht.
6. Modals/Dropdowns rendern am **Body-Root** (außerhalb des Main-Containers) → bei „nicht gefunden" Voll-Snapshot `depth:3`.
7. Tab kann zwischendurch schließen („Target page has been closed") → Connection neu anfordern (`browser_snapshot`).
8. **File-Upload (D11) geht NICHT über `playwright-live`**: der Extension-/CDP-Relay blockt `DOM.setFileInputFiles` (`Not allowed`). Datei muss zudem unter einem Allowed-Root liegen (Repo-Verzeichnis), nicht `%TEMP%`. → D11 via Tier-1-API (Token) oder Tandem (User legt Datei selbst ab) verifizieren, nicht via Live-Browser.

## Deploy-/Migrations-Fallen (Fork-spezifisch)

- **CI ≠ Deploy.** `azure-acr-build.yaml` baut+pusht nur das Image (Tags: `git-<sha>`, `build-<run>-<date>`; `latest` **nur** auf `main`). Das k8s-Rollout (`kubectl set image`) ist ein separater Schritt.
- **`rollout status`-Timeout ≠ Fehlschlag.** Alembic-Migration läuft **vor** dem Readiness-Probe-Fenster und überschreitet es bei großen Upstream-Sprüngen → erneut `rollout status` aufrufen, Pod-`ready`+Log prüfen. (`preflight` macht den Retry automatisch.)
- **Migration-Log: vollen Boot-Log prüfen, nicht `--tail`.** Single-Head verifizieren (lokal: `migrations/versions/*.py` parsen → genau 1 Revision ohne ist-down_revision; vgl. `alembic-merge`-Skill).
- **Bekannt-benign ERROR (kein Blocker):** `socket.main:periodic_session_pool_cleanup - Unable to renew session cleanup lock. Exiting.` = Redis-Session-Lock-Layer, **nicht** die DB. `preflight` filtert ihn aus. Siehe brain `reference_sync_redis_on_loop_podkill.md`.
- **DB-Wipe braucht Redis-Flush mit** (sonst Geister-Sessions) — brain `owui-db-wipe-flush-redis.md`.
- **UTF-8-Doppel-Encoding** bei JSON-Feldern — brain `owui-json-utf8-double-encoding.md`.
- **Postgres vs SQLite:** Fork-Deployments fahren Postgres (Pool/Session-Sharing-Env). `JSONField` muss native dict/list von JSONB durchlassen (sonst HTTP 500). SQLite-Pfad unbetroffen.

## Feature-Gates (N/A ≠ Fehler)

Manche Fork-Features sind config-gated und korrekt versteckt, wenn die Flags aus sind:

| Feature | Gate (in `/api/config` features) | Aktivierung |
|---------|----------------------------------|-------------|
| SharePoint/Graph-KB-Import | `enable_onedrive_integration` **und** `enable_onedrive_business` | Admin: OneDrive-Integration + Business + `ONEDRIVE_CLIENT_ID_BUSINESS` |

`plan` markiert solche Checks als **N/A**, nicht fail — solange das Flag in `instances.json` `expected_features` als `false` steht.

## Neue Instanz hinzufügen

1. Block in `instances.json` kopieren, Cluster-Koordinaten + `expected_features` setzen.
2. `./deploy-test.sh preflight <neu>` — Tier 0 sofort nutzbar.
3. Erster Lauf hat leeren State → `plan` lässt alle Tier-2-Checks laufen (korrekt: nichts ist verifiziert).
