# Plan: Was nach dem On-Prem-Rollout im Fork offen ist

Stand 2026-08-03. Der `SHAREPOINT_BACKEND=onprem`-Pfad ist bei KHKI produktiv
(`git-d27e73e`, Helm-Revision 8) — Backend, Migration und Credential-Store messbar in
Ordnung. Beim ersten Nutzerkontakt fiel auf: **das Feature ist über die Oberfläche gar
nicht erreichbar.** Dieses Dokument sammelt die Lücken, die dabei sichtbar wurden, und
gehört zu [`LDAP_SHAREPOINT_BACKEND.md`](LDAP_SHAREPOINT_BACKEND.md).

Alle Befunde sind am laufenden Pod bzw. am Quelltext gemessen, nicht abgeleitet.

| # | Problem | Wirkung | Größe | Stand |
|---|---|---|---|---|
| P1 | Picker hängt am OneDrive-/Entra-Gate | **Feature unbenutzbar** | klein | erledigt 2026-08-03 |
| P2 | Kein Frontend für Status/Widerspruch | Widerspruch nur per API | mittel | erledigt 2026-08-03 |
| P3 | Update-Hinweis zeigt Upstream-Release | irreführend | klein | erledigt 2026-08-03 |
| P4 | `feature/owui-0.11.0` existiert nur lokal | Bus-Faktor 1 | organisatorisch | hinfällig, siehe unten |

> **Nachtrag 2026-08-03.** P1–P3 sind auf `feature/ldap-sharepoint-credential` (0.10.2)
> umgesetzt; Umsetzungsbericht in
> [`.claude/PRPs/reports/PLAN_SHAREPOINT_ONPREM_UI_GAPS-report.md`](../.claude/PRPs/reports/PLAN_SHAREPOINT_ONPREM_UI_GAPS-report.md).
> P4 war beim Schreiben dieses Plans bereits überholt — die Messung dazu steht unten.

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

- [x] `/api/config` liefert `enable_sharepoint_import` unabhängig von jedem OneDrive-Flag
- [x] Picker erscheint bei `SHAREPOINT_BACKEND=onprem` **ohne** gesetzte Entra-Variablen
- [x] Graph-Instanz mit alter Konfiguration sieht ihn unverändert (Regressionstest)
- [x] `FORK_CHANGES.md` nennt die Injection-Stelle in `main.py`

Umgesetzt wie beschrieben, mit einem Zusatz: `SHAREPOINT_BACKEND.strip() != ''`, damit ein
versehentliches `SHAREPOINT_BACKEND=" "` nicht als eingeschaltet zählt — der Resolver in
`utils/sharepoint_backend.py:87` strippt ohnehin. Die drei Zusicherungen oben sind in
`test/sharepoint/test_sharepoint_backend_compat.py::TestSharePointPickerStaysVisibleOnGraph`
festgenagelt, inklusive der Gegenprobe, dass `SHAREPOINT_BACKEND=''` OneDrive **nicht**
mit abschaltet.

---

## P2 — Kein Frontend für Status, Widerspruch und Löschen

Die Endpunkte stehen (`/api/v1/users/user/credentials/status`, `.../opt-in`), aber
`grep -rl 'credentials/status' src/` findet nichts. Es gibt keine Oberfläche dazu.

Das Feature legt AD-Kennwörter verschlüsselt ab, **Speichern ist der Standard**, und der
Widerspruch ist derzeit nur per API erreichbar. Für einen Pilotbetrieb tragbar, als
Dauerzustand nicht: wer widersprechen will, muss dafür einen HTTP-Aufruf absetzen können.

Gehört in die Kontoeinstellungen: Status anzeigen (verwahrt ja/nein, welches Konto, wie
lange noch), Widerspruch umschalten, Eintrag löschen. Kein neuer Endpunkt nötig.

### Umgesetzt

`src/lib/components/chat/Settings/Account/CredentialStore.svelte`, eingehängt in
`Settings/Account.svelte` neben „Passwort ändern". Aufklappbar wie die übrigen Blöcke dort;
zeigt Konto, Ablauf und letzte Verwendung, einen Schalter für den Widerspruch und — nur wenn
etwas verwahrt ist — einen Löschknopf. Die drei bestehenden Endpunkte reichten, wie im Plan
angenommen; hinzu kamen nur die Client-Funktionen in `src/lib/apis/users/index.ts`.

**Ein zusätzliches Backend-Flag war doch nötig.** Der Status-Endpunkt kann nicht als Gate
dienen: er liefert `exists=false, opted_in=true` sowohl bei abgeschaltetem Speicher als auch
bei eingeschaltetem, aber noch leerem (`models/user_credentials.py:345`). Beides ist von
außen ununterscheidbar, der Block wäre also auf jeder fremden Instanz erschienen. Deshalb
`features.enable_ldap_credential_store` in `/api/config`, analog zu P1.

Die deutschen Texte stehen in `de-DE`; die übrigen 62 Locales fallen auf den englischen
Schlüsseltext zurück. Ein `npm run i18n:parse` hätte alle 63 Dateien angefasst und gehört in
einen eigenen Commit.

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

### Umgesetzt

Der zweite Weg: `ENABLE_VERSION_UPDATE_CHECK` steht in `env.py` jetzt per Default auf
`'false'` statt `'true'`. Die Abfrage-URL blieb unangetastet — wer den Upstream-Vergleich
sehen will, setzt die Variable auf `true` und bekommt exakt das alte Verhalten. Sobald der
Fork eigene Releases taggt, ist der ehrlichere erste Weg ein Einzeiler an derselben Stelle.

Der Default ist ein **Overlay** auf eine Upstream-Zeile und überlebt einen Merge nicht von
selbst; Detektor steht in `FORK_CHANGES.md` unter `env.py`.

---

## P4 — ~~`feature/owui-0.11.0` liegt auf genau einer Maschine~~ hinfällig

**Die Prämisse stimmt nicht mehr.** Gemessen am 2026-08-03:

```
git merge-base --is-ancestor feature/owui-0.11.0 main   -> ja
git rev-list --count main..feature/owui-0.11.0          -> 0
git rev-parse main neurawork/main                       -> 73f5ab2f4 == 73f5ab2f4
```

`feature/owui-0.11.0` (62be7e6e) ist restlos in `main` enthalten, und `main` steht auf
0.11.0 und ist gepusht. Der Branch trägt keinen einzigen Commit, den `main` nicht hätte —
er ist nur ein zurückgebliebener Zeiger. `feature/live-custom-css` steckt ebenfalls in
`main` (und *nicht* im 0.11-Branch). Es ist also nichts ungesichert; der Bus-Faktor ist weg.

| Branch | Version | Remote | in `main`? |
|---|---|---|---|
| `main` | 0.11.0 | `neurawork` (identisch) | — |
| `feature/owui-0.11.0` | 0.11.0 | keins — **egal**, 0 eigene Commits | ja |
| `feature/live-custom-css` | 0.11.0 | `neurawork` | ja |
| `feature/ldap-sharepoint-credential` | 0.10.2 | `origin` + `neurawork` | **nein** |

Auch `CLAUDE.md` §1 ist an dieser Stelle veraltet („Latest upstream merge … Not yet on
`main`").

### Was stattdessen offen ist

Die andere Hälfte: **die LDAP-/SharePoint-Arbeit ist nie auf 0.11 vorgezogen worden.**
`main` liegt 691 Commits vor dem KHKI-Branch, dieser 14 (jetzt 15) vor `main` — und keiner
davon ist in `main`. Für KHKI ist das derzeit richtig so, die Instanz fährt 0.10.2; aber
jede weitere 0.10.2-Arbeit vergrößert den Rückportier-Abstand.

Der Cherry-Pick auf `main` ist damit ein eigener Zuschnitt, kein Nebensatz von P4 — die
0.11-Oberfläche wurde umgebaut (`AdminSettingRow`/`AdminSettingField`, siehe
`UPSTREAM_0.11.0_TRIAGE.md`), die Frontend-Teile von P1/P2 werden dort nicht sauber
auftragen.

---

## Reihenfolge

1. ~~**P4 pushen**~~ — hinfällig, war bereits über `main` gesichert
2. **P1** ✅ — schaltet das Feature überhaupt erst frei; ohne P1 ist die Abnahme des
   KHKI-Runbooks (§6.3–§6.6, insbesondere die Rechtetrennung) nicht durchführbar
3. **P3** ✅ — Einzeiler, mit P1 im selben Build
4. **P2** ✅ — vorgezogen und mit erledigt, statt auf das Ende des Pilotbetriebs zu warten

P1–P3 liegen in einem Build. Damit wird bei KHKI ein zweites Mal deployed und die offene
Abnahme kann laufen.

## Was danach noch offen ist

- **Deploy + Abnahme bei KHKI** — der Build ist gebaut und getestet, aber nicht ausgerollt.
  Erst der laufende Pod belegt, dass der Picker erscheint; bis dahin ist P1 „umgesetzt",
  nicht „bestätigt". Ablauf: `PLAYWRIGHT_DEPLOY_SMOKE_PROTOCOL.md`.
- **Vorziehen auf 0.11** — siehe P4 oben. Eigener Zuschnitt.
- **`CLAUDE.md` §1** behauptet weiterhin, 0.11.0 sei nicht auf `main`. Beim nächsten
  Anfassen mitkorrigieren.
