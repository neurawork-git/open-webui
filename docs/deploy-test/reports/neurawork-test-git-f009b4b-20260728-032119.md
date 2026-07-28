# Deploy-Test-Report — neurawork-test @ `git-f009b4b`

- Erzeugt: 2026-07-28T01:21:20Z
- Instanz: `neurawork-test`
- Image-Tag: `git-f009b4b`

| Check | Tier | Ergebnis | Verifiziert @ | Notiz |
|-------|------|----------|---------------|-------|
| T0-config — /api/config liefert features + erwartete Flags | T0 | ✅ pass | `git-f009b4b` |  |
| T0-health — /health == 200 | T0 | ✅ pass | `git-f009b4b` |  |
| T0-image — Image-Tag == erwarteter Build | T0 | ✅ pass | `git-f009b4b` | neuraworkacr.azurecr.io/open-webui:git-f009b4b |
| T0-migration — Alembic-Kette ohne Error auf Single-Head | T0 | ✅ pass | `git-f009b4b` |  |
| T0-rollout — Rollout fertig, Pod ready, 0 restarts | T0 | ✅ pass | `git-f009b4b` |  |
| T0-version — /api/version == erwartete Version | T0 | ✅ pass | `git-f009b4b` | {"version":"0.11.0","deployment_id":""} |
| T1-custom-css — Live-Custom-CSS: /static/custom.css kommt aus der DB (nosniff+ETag statt StaticFiles), POST-Round-Trip, 256-KiB-Cap, 401 ohne Token | T1 | ✅ pass | `git-f009b4b` | In-Pod-Round-Trip gegen Postgres: GET stylesheet 200 mit nosniff+eigenem ETag (Route schlaegt /static-Mount), POST -> Stylesheet identisch, 300 KiB -> 400, ohne Token -> 401, danach auf leer zurueckgesetzt |
| T1-kb-api — GET /api/v1/knowledge liefert Sammlungen | T1 | — — | `—` |  |
| T1-models-api — GET /api/models liefert nicht-leere Liste | T1 | — — | `—` |  |
| D1-auth — Login/Session, kein /auth-Redirect, Username korrekt | T2 | ✅ pass | `git-f156336` |  |
| D10-admin-docs — Admin Settings/Documents: RAG-Engine/Embedding-Config lädt | T2 | ✅ pass | `git-f156336` |  |
| D11-upload — File-Upload im Chat -> Verarbeitung -> nutzbar | T2 | ✅ pass | `git-f156336` |  |
| D12-channels — Channel öffnen, Historie + Senden | T2 | — — | `—` |  |
| D2-chat — Chat-Inferenz E2E (Prompt -> Antwort, persistiert, Auto-Titel) | T2 | — — | `—` |  |
| D3-models-ui — Modell-Selector lädt Liste + Fork-Gruppen | T2 | — — | `—` |  |
| D4-knowledge — Workspace/Knowledge-Liste rendert | T2 | — — | `—` |  |
| D5-kb-open — KB öffnen, Dateien + Fork-Buttons (RAG/Zugriff/Neu-indizieren) | T2 | ✅ pass | `git-f156336` |  |
| D6-sharepoint — SharePoint/Graph-Import-Picker | T2 | — — | `—` |  |
| D7-rag — RAG-Retrieval im Chat: # KB-Ref -> Quellen abgerufen + Inline-Zitate | T2 | — — | `—` |  |
| D8-rag-settings — Per-KB RAG-Settings-Override (BM25/Hybrid/Reranker/Full-Context) | T2 | ✅ pass | `git-f156336` |  |
| D9-processing — Admin Document-Processing-Dashboard (Stats + Tabelle + Chunk-Progress) | T2 | ✅ pass | `git-f156336` |  |

**Summe:** 13 pass · 0 fail · 21 Checks gesamt
