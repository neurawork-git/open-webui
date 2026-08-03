# Plan: Was nach dem On-Prem-Rollout im Fork offen ist

Stand 2026-08-03. Der `SHAREPOINT_BACKEND=onprem`-Pfad ist bei KHKI produktiv
(`git-d27e73e`, Helm-Revision 8) — Backend, Migration und Credential-Store messbar in
Ordnung. Beim ersten Nutzerkontakt fiel auf: **das Feature ist über die Oberfläche gar
nicht erreichbar.** Dieses Dokument sammelt die Lücken, die dabei sichtbar wurden, und
gehört zu [`LDAP_SHAREPOINT_BACKEND.md`](LDAP_SHAREPOINT_BACKEND.md).

Alle Befunde sind am laufenden Pod bzw. am Quelltext gemessen, nicht abgeleitet.

| # | Problem | Wirkung | Größe |
|---|---|---|---|
| P1 | Picker hängt am OneDrive-/Entra-Gate | **Feature unbenutzbar** | klein |
| P2 | Kein Frontend für Status/Widerspruch | Widerspruch nur per API | mittel |
| P3 | Update-Hinweis zeigt Upstream-Release | irreführend | klein |
| P4 | `feature/owui-0.11.0` existiert nur lokal | Bus-Faktor 1 | organisatorisch |

---

## P1 — Der SharePoint-Picker ist ohne Entra unerreichbar

**Das ist der Blocker.** Backend fertig, Oberfläche zeigt nichts.

`src/lib/components/workspace/Knowledge/KnowledgeBase.svelte:1805`:

```svelte
showSharePointImport={!isExternalKnowledge &&
    $config?.features?.enable_onedrive_integration &&
    $config?.features?.enable_onedrive_business}
```

Die beiden Flags kommen aus `backend/open_webui/main.py:1954-1959`, und `config.py:842-854`
zeigt, woran sie hängen:

```python
ENABLE_ONEDRIVE_INTEGRATION = os.getenv('ENABLE_ONEDRIVE_INTEGRATION', 'False') == 'true'
ENABLE_ONEDRIVE_BUSINESS    = os.getenv('ENABLE_ONEDRIVE_BUSINESS', 'True') == 'true' \
                              and bool(ONEDRIVE_CLIENT_ID_BUSINESS)
```

`ONEDRIVE_CLIENT_ID_BUSINESS` ist eine **Entra-App-ID**. Eine On-Prem-Farm hat keine. Das
Backend wurde auf NTLM umgestellt, das Frontend-Gate blieb am Graph-Pfad hängen — der
`onprem`-Modus ist damit strukturell unerreichbar, nicht bloß falsch konfiguriert.

Verschärfend: `enable_onedrive_business` wird nur dann überhaupt in die Antwort gelegt,
wenn `onedrive.enable` wahr ist (`main.py:1955-1963` — bedingtes Dict-Spread). Bei
ausgeschaltetem OneDrive ist der Schlüssel also **nicht false, sondern nicht vorhanden**.
Das erklärt, warum `/api/config` bei KHKI gar keinen `onedrive`-Block liefert.

Belegt am laufenden Pod: alle sechs Feature-Variablen gesetzt, alle zehn
`/sharepoint/*`-Routen vorhanden, Menüpunkt trotzdem nie gerendert.

### Fix

Ein eigenes Flag, hergeleitet aus dem Backend-Modus statt aus OneDrive:

```python
# main.py, im features-Block
'enable_sharepoint_import': SHAREPOINT_BACKEND != '',
```

```svelte
showSharePointImport={!isExternalKnowledge &&
    $config?.features?.enable_sharepoint_import}
```

`SHAREPOINT_BACKEND` steht in `env.py:832` und ist per Default `'graph'` — bestehende
Graph-Instanzen bekommen das Flag also wahr und sehen den Picker weiter. Das ist die
Verhaltensgleichheit, die §9 des KHKI-Runbooks zusichert; sie gehört in die
Kompatibilitätstests (`test/sharepoint/test_sharepoint_backend_compat.py`).

Wer den Import gezielt abschalten will, setzt `SHAREPOINT_BACKEND=''`.

**Was hier nicht getan werden sollte:** `ONEDRIVE_CLIENT_ID` mit einem Platzhalter zu
füllen, um das Gate zu öffnen. Das schaltet denselben Schalter für die OneDrive-Einträge
mit — die erscheinen dann im Menü und laufen mangels Entra ins Leere. Ein sichtbarer,
kaputter Menüpunkt ist schlechter als gar keiner.

### Erledigt, wenn

- [ ] `/api/config` liefert `enable_sharepoint_import` unabhängig von jedem OneDrive-Flag
- [ ] Picker erscheint bei `SHAREPOINT_BACKEND=onprem` **ohne** gesetzte Entra-Variablen
- [ ] Graph-Instanz mit alter Konfiguration sieht ihn unverändert (Regressionstest)
- [ ] `FORK_CHANGES.md` nennt die Injection-Stelle in `main.py`

---

## P2 — Kein Frontend für Status, Widerspruch und Löschen

Die Endpunkte stehen (`/api/v1/users/user/credentials/status`, `.../opt-in`), aber
`grep -rl 'credentials/status' src/` findet nichts. Es gibt keine Oberfläche dazu.

Das Feature legt AD-Kennwörter verschlüsselt ab, **Speichern ist der Standard**, und der
Widerspruch ist derzeit nur per API erreichbar. Für einen Pilotbetrieb tragbar, als
Dauerzustand nicht: wer widersprechen will, muss dafür einen HTTP-Aufruf absetzen können.

Gehört in die Kontoeinstellungen: Status anzeigen (verwahrt ja/nein, welches Konto, wie
lange noch), Widerspruch umschalten, Eintrag löschen. Kein neuer Endpunkt nötig.

---

## P3 — Der Update-Hinweis vergleicht gegen Upstream

`main.py:2178` fragt

```
https://api.github.com/repos/open-webui/open-webui/releases/latest
```

Der Fork meldet damit „0.11 verfügbar", während er selbst 0.10.2 fährt. Für einen Fork ist
diese Anzeige strukturell falsch: das dort genannte Release lässt sich nicht einspielen,
die Fork-Änderungen sind nicht darin.

Zwei Wege. Entweder gegen die **Fork**-Releases prüfen, oder
`ENABLE_VERSION_UPDATE_CHECK` für Fork-Builds auf `False` vordefinieren. Ersteres ist
nützlicher, sobald der Fork Releases taggt; bis dahin ist Letzteres ehrlicher.

Kein Blocker, aber jeder Kunde fragt danach — KHKI hat es am ersten Tag gemeldet.

---

## P4 — `feature/owui-0.11.0` liegt auf genau einer Maschine

| Branch | Version | Remote |
|---|---|---|
| `feature/ldap-sharepoint-credential` | 0.10.2 | `origin` + `neurawork` |
| `feature/owui-0.11.0` | 0.11.0 | **keins** |

688 Commits, die der 0.11-Branch dem KHKI-Branch voraus hat; 13 in der Gegenrichtung. Die
Merge-Arbeit steckt in `UPSTREAM_0.11.0_TRIAGE.md` und ist real geleistet — sie liegt nur
ungesichert lokal. Geht die Arbeitsstation verloren, ist sie weg.

Erst pushen, dann die 13 LDAP-Commits darauf cherry-picken. In dieser Reihenfolge, damit
der Cherry-Pick auf einem gesicherten Stand aufsetzt.

---

## Reihenfolge

1. **P4 pushen** — billig, sichert vorhandene Arbeit, blockiert nichts
2. **P1** — schaltet das Feature überhaupt erst frei; ohne P1 ist die Abnahme des
   KHKI-Runbooks (§6.3–§6.6, insbesondere die Rechtetrennung) nicht durchführbar
3. **P3** — Einzeiler, kann mit P1 in denselben Build
4. **P2** — eigener Zuschnitt, vor dem Ende des Pilotbetriebs

P1 und P3 zusammen ergeben einen Build; damit wird bei KHKI ein zweites Mal deployed und
die offene Abnahme kann laufen.
