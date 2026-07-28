# Deploy-Test-Report — neurawork-prod @ `git-f009b4b`

- Erzeugt: 2026-07-28T10:17:19Z
- Instanz: `neurawork-prod`
- Image-Tag: `git-f009b4b`

| Check | Tier | Ergebnis | Verifiziert @ | Notiz |
|-------|------|----------|---------------|-------|
| T0-config — /api/config liefert features + erwartete Flags | T0 | ✅ pass | `git-f009b4b` |  |
| T0-health — /health == 200 | T0 | ✅ pass | `git-f009b4b` |  |
| T0-image — Image-Tag == erwarteter Build | T0 | ✅ pass | `git-f009b4b` | neuraworkacr.azurecr.io/open-webui:git-f009b4b |
| T0-migration — Alembic-Kette ohne Error auf Single-Head | T0 | ✅ pass | `git-f009b4b` | ad192b50687b, merge upstream v0.11.0 |
| T0-rollout — Rollout fertig, Pod ready, 0 restarts | T0 | ✅ pass | `git-f009b4b` |  |
| T0-version — /api/version == erwartete Version | T0 | ✅ pass | `git-f009b4b` | {"version":"0.11.0","deployment_id":""} |
| T1-custom-css — Live-Custom-CSS: /static/custom.css kommt aus der DB (nosniff+ETag statt StaticFiles), POST-Round-Trip, 256-KiB-Cap, 401 ohne Token | T1 | ✅ pass | `git-f009b4b` | In-Pod-Round-Trip gegen die Live-DB: stylesheet 200 mit nosniff+eigenem ETag (Route schlaegt /static-Mount), POST byte-identisch zurueck, 300 KiB -> 400, ohne Token -> 401, danach auf leer zurueckgesetzt (config-Wert verifiziert) |
| T1-kb-api — GET /api/v1/knowledge liefert Sammlungen | T1 | — — | `—` |  |
| T1-models-api — GET /api/models liefert nicht-leere Liste | T1 | — — | `—` |  |
| D1-auth — Login/Session, kein /auth-Redirect, Username korrekt | T2 | ✅ pass | `git-75d4416` |  |
| D10-admin-docs — Admin Settings/Documents: RAG-Engine/Embedding-Config lädt | T2 | ✅ pass | `git-75d4416` | Azure embed text-embedding-3-large, markitdown extern, Force-KB-on-toolcall AN, Top-K5/Hybrid |
| D11-upload — File-Upload im Chat -> Verarbeitung -> nutzbar | T2 | ⏭ skip | `git-75d4416` | playwright-live Extension blockt DOM.setFileInputFiles (CDP-Security); via Tier-1-API od. Tandem verifizierbar |
| D12-channels — Channel öffnen, Historie + Senden | T2 | ✅ pass | `git-75d4416` | #test Channel laedt + Nachricht gepostet (WebSocket) |
| D2-chat — Chat-Inferenz E2E (Prompt -> Antwort, persistiert, Auto-Titel) | T2 | ✅ pass | `git-75d4416` | DEPLOY-OK 0.9.6, auto-title |
| D3-models-ui — Modell-Selector lädt Liste + Fork-Gruppen | T2 | ✅ pass | `git-75d4416` |  |
| D4-knowledge — Workspace/Knowledge-Liste rendert | T2 | ✅ pass | `git-75d4416` |  |
| D5-kb-open — KB öffnen, Dateien + Fork-Buttons (RAG/Zugriff/Neu-indizieren) | T2 | ✅ pass | `git-75d4416` |  |
| D6-sharepoint — SharePoint/Graph-Import-Picker | T2 | ⚪ na | `git-75d4416` | feature-gated: enable_onedrive_* |
| D7-rag — RAG-Retrieval im Chat: # KB-Ref -> Quellen abgerufen + Inline-Zitate | T2 | ✅ pass | `git-75d4416` | 3 Quellen, Inline-Zitat 01-what-is-openwebui.md |
| D8-rag-settings — Per-KB RAG-Settings-Override (BM25/Hybrid/Reranker/Full-Context) | T2 | ✅ pass | `git-75d4416` | BM25/Hybrid/Reranker/FullContext Modal |
| D9-processing — Admin Document-Processing-Dashboard (Stats + Tabelle + Chunk-Progress) | T2 | ✅ pass | `git-75d4416` | Dashboard live, Chunk-Progress, 2 Failed historisch |

**Summe:** 17 pass · 0 fail · 21 Checks gesamt
