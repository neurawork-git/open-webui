# Plan: LDAP-/SharePoint-Feature auf 0.11.0 vorziehen

> Vorwärts-Portierung, kein Upstream-Merge. `feature/ldap-sharepoint-credential`
> (0.10.2, 17 Commits, bei KHKI produktiv) soll auf `main` (0.11.0, 73f5ab2f4) landen.
>
> Gehört zu [`LDAP_SHAREPOINT_BACKEND.md`](LDAP_SHAREPOINT_BACKEND.md) und schließt den
> Punkt „Vorziehen auf 0.11" aus [`PLAN_SHAREPOINT_ONPREM_UI_GAPS.md`](PLAN_SHAREPOINT_ONPREM_UI_GAPS.md).
> Migrationsteil strikt nach [`ALEMBIC_MERGE_PLAYBOOK.md`](ALEMBIC_MERGE_PLAYBOOK.md).

**Grundlage ist eine echte Merge-Probe**, nicht eine Abschätzung: ein
`git merge --no-commit --no-ff` auf einen Wegwerf-Branch von `main`, ausgewertet und wieder
abgebrochen. Wo die Probe der Vorab-Erwartung widerspricht, gilt die Probe. Das ist an den
betroffenen Stellen ausdrücklich vermerkt.

| # | Sache | Erwartung vorher | **Gemessen** | Größe |
|---|---|---|---|---|
| M1 | Strategie | Cherry-Pick / Neu-Anwenden | **`git merge` — Historien verwandt, Basis `f805abeee`** | — |
| M2 | Konfliktfläche | „viele Hotspots" | **3 Dateien, 8 Regionen, davon 5 in einer Doku-Datei** | klein |
| M3 | `utils/middleware.py` | höchstes Risiko | **0 Konflikte** | — |
| M4 | `routers/knowledge.py` | höchstes Risiko | **0 Konflikte** | — |
| M5 | `env.py` | harter Konflikt erwartet | **0 Konflikte** | — |
| M6 | Alembic | — | **zwei Heads, kein Konflikt gemeldet** | mittel, Pflicht |
| M7 | Favicons | Ausschluss angeordnet | **merged sauber, überschreibt Fork-Branding** | klein, Pflicht |
| M8 | Picker-Gate | „reiner Fix" | **schaltete den Picker bei *jedem* Kunden sichtbar** | ~~Entscheidung~~ **behoben vor dem Port** |
| M9 | Frontend-Optik | offen | **kompiliert, sieht aber nach 0.10.2 aus** | ~90 min |

---

## 1. Was die Merge-Probe belegt

```
git merge-base main feature/ldap-sharepoint-credential   -> f805abeee05f8899baf30d006abd964567d01198
git rev-list --left-right --count main...feature/…       -> 691  17
git merge --no-commit --no-ff feature/ldap-sharepoint-credential
git diff --name-only --diff-filter=U                     -> 3 Dateien
```

28 von 31 Dateien mergen sauber. Alle drei Konflikte sind reine Inhaltskonflikte
(`git ls-files -u` zeigt Stufen 1/2/3 — kein add/add, kein delete/modify, kein Rename).
`diff3` ist als Konfliktstil konfiguriert, deshalb ist die Merge-Basis-Seite jedes Hunks
sichtbar: **sie ist bei allen drei Code-Konflikten leer.** Beide Seiten fügen also nur
hinzu. Die Auflösung lautet überall „beide behalten, neu sortieren".

Die gefürchteten Dateien haben nicht konfligiert, und das kehrt die bisherige Einschätzung
um:

- **`utils/middleware.py`** — die Datei mit der höchsten Änderungsrate im Repo (99,7. Perzentil),
  `main` hat hier seit der Basis 1081 Zeilen bewegt. **Null Konflikte.** Beide
  `__sharepoint__`-Injektionen liegen intakt, weil der Fork sie an
  `'__oauth_token__': await get_system_oauth_token(request, user),` verankert — eine Zeile,
  die 0.11.0 an beiden Stellen unberührt gelassen hat.
- **`routers/knowledge.py`** — 162 vom Fork geänderte Zeilen, `main` hat hier seit der Basis
  nur 19 bewegt. Null Konflikte, und semantisch geprüft statt nur textuell: Greps auf
  `_get_microsoft_access_token`, nacktes `GraphClient` und `OAuthSessions` liefern im
  gemergten Baum **Exit 1** — die entfernte Hilfsfunktion hinterlässt keine hängende
  Referenz. Alle 9 Aufrufstellen von `_translate_graph_error` sind korrekt `raise await …`.
- **`env.py`, `routers/users.py`, `routers/auths.py`** — null Konflikte, alle Fork-Haken
  wörtlich übernommen. Insbesondere der erwartete Zusammenstoß am
  `ENABLE_OAUTH_TOKEN_EXCHANGE`-Anker ist **nicht eingetreten**.
- **Routenreihenfolge FastAPI** ist unkritisch: die drei neuen Credential-Routen liegen in
  `users.py` bei 534/548/578, der `/{user_id}`-Auffangpfad bei 827.
- `python -m py_compile` läuft auf allen neun automatisch gemergten bzw. neuen Python-Dateien
  durch.

**Was die Probe *nicht* belegt:** Es lief keine Testsuite, kein `npm run check`, kein
`alembic`, kein Anwendungsstart gegen den gemergten Baum. „Mergt und kompiliert" ist bewiesen,
„verhält sich richtig" nicht. Genau dort liegen die Schritte 8–14.

### Warum Merge und nicht Cherry-Pick

Die Historien sind verwandt. Ein Cherry-Pick müsste Hunks von Hand in Dateien einfädeln, die
der Merge kostenlos auflöst. Und jede Variante über einen zweigweiten Diff
(`git diff … | git apply`) ist **destruktiv**: relativ zum Quellbranch lesen sich die acht
0.11-Migrationen von `main` (`55f1302ac17c`, `856c5b02fb54`, `959eaac8f909`, `9a1b2c3d4e5f`,
`ad192b50687b`, `b0018471bbbe`, `c49178636c78`, `f0bd01a18a3d`) als Löschungen. Dasselbe gilt
für `docs/` (siehe §6).

---

## 2. Die drei Konflikte im Einzelnen

### 2.1 `backend/open_webui/main.py` — eine Region, drei Zeilen

Beide Seiten schieben einen Namen in denselben alphabetischen Platz der
`from open_webui.env import (`-Liste, zwischen `ENABLE_EASTER_EGGS,` und
`EXTERNAL_PWA_MANIFEST_URL,`:

```
<<<<<<< HEAD
    ENABLE_PLUGINS,
||||||| f805abeee
=======
    # LDAP credential store (fork)
    ENABLE_LDAP_CREDENTIAL_STORE,
>>>>>>> feature/ldap-sharepoint-credential
```

Basisseite leer → beide behalten, alphabetisch sortiert. Alles Übrige in `main.py` hat sich
automatisch gemergt: der `SHAREPOINT_BACKEND`-Import und beide Feature-Schlüssel in
`get_app_config` (gemessen bei 2231/2235, **außerhalb** des bedingten
`onedrive.enable`-Dict-Spreads — das ist die Bedingung aus `FORK_CHANGES.md` §6).

### 2.2 `src/lib/i18n/locales/de-DE/translation.json` — zwei Regionen

Gleiches Muster, gleiche leere Basisseite:

| Region | HEAD (0.11) | Fork |
|---|---|---|
| ~686, nach `"Created on {{date}}"` | `"Credential used for Document Intelligence."`, `"Credentials used to authenticate with the Jupyter server."` | `"Credential storage turned off. Any stored password was deleted."` |
| ~1533, nach `"Last reply"` | `"Last run"` | `"Last used"` |

Alles behalten, alphabetisch einsortieren. Nur 2 der 11 neuen Credential-Schlüssel haben
konfligiert, die übrigen 9 sind automatisch gelandet. Solange die Marker drinstehen, ist die
Datei **kein gültiges JSON** — jeder Frontend-Lauf in diesem Fenster scheitert laut, nicht
leise.

### 2.3 `docs/FORK_CHANGES.md` — fünf Regionen, aber Wegwerf-Arbeit

Marker bei 36, 70, 84, 203, 228. Beide Seiten haben dieselben Inventarzeilen umgeschrieben:
`main` für 0.11.0, der Fork für das LDAP-Feature. Es ist Prosa, kein Code — und Fork-Politik
verlangt ohnehin, diese Datei nach jedem Merge **neu zu erzeugen** (CLAUDE.md §5,
Skill `alembic-merge`). Deshalb wird sie in Schritt 6 pauschal auf die HEAD-Fassung gesetzt
und in Schritt 15 von Hand neu geschrieben — nicht Region für Region gemergt.

Bemerkenswert: die beiden Seiten widersprechen sich in einer **Tatsache**. HEAD sagt, der
Test `src/lib/utils/onedrive-file-picker.test.ts` sei rot; der Fork-Branch sagt, Commit
`bb5c65cc4` habe ihn repariert. Der Fork ist die neuere Wahrheit, Schritt 12 belegt sie.

---

## 3. Was der Merge *nicht* meldet

Das ist die eigentliche Gefahr. Drei Dinge fahren mit oder brechen, ohne dass Git je
nachfragt.

### 3.1 Alembic zerfällt in zwei Heads

Git meldet die Migration als sauber hinzugefügt, der DAG bricht trotzdem:

```
e7f8a9b0c1d2 (Fork)      down_revision = "e48721182479"
ad192b50687b (main)      down_revision = ("e48721182479", "f0bd01a18a3d")
```

Beide zweigen von `e48721182479` ab, und nichts referenziert eines der beiden als
`down_revision`. `alembic upgrade head` bricht mit „Multiple head revisions are present" ab,
die Tabelle `user_credential` entsteht nie.

**Zur Klarstellung:** `main` allein hat genau **einen** Head (`ad192b50687b`) und null
hängende `down_revision`-Verweise — nachgeprüft durch Parsen aller 64 Revisionsdateien. Der
an anderer Stelle behauptete verwaiste Head `a2b3c4d5e6f7` **existiert nicht**; dem nicht
nachgehen.

Behebung ausschließlich per `alembic merge` (Schritt 8). Das Umhängen von
`e7f8a9b0c1d2.down_revision` ist verboten, siehe §6.

### 3.2 Die Favicons werden still überschrieben

`git status --porcelain` zeigt nach dem Merge `M backend/open_webui/static/favicon.ico` und
`favicon.png` — **ohne Konflikt, ohne Warnung**. Über fünf Refs gemessen:

| Ref | favicon.ico | favicon.png |
|---|---|---|
| `main` | `14c5f9c6d437…` (15086 B) | `63735ad4616f…` (10655 B) |
| Quellbranch | `b819d42f96d1…` (4286 B) | `10c84f440ced…` (21666 B) |
| Upstream `v0.10.2` / `v0.11.0` | identisch mit Quellbranch | identisch mit Quellbranch |

Der Quellbranch trägt also die **Stock-Icons von Open WebUI**, `main` das Fork-Branding.
Portieren heißt hier nicht „Branding mitnehmen", sondern „Branding löschen". Es ist
Kollateralschaden des bekannten Defekts aus `UPSTREAM_0.11.0_TRIAGE.md` §5.1 (`config.py`
räumt beim Import jede lose Datei in `STATIC_DIR` weg und füllt aus dem Frontend-Build nach).

Folge für den ganzen Port: **`git add -A` ist verboten.** Nach *jedem* Backend-Lauf
(pytest, alembic, Anwendungsstart) muss `git status backend/open_webui/static/` erneut
geprüft werden.

### 3.3 Das Picker-Gate wird für alle Kunden aufgemacht

> **Erledigt am 2026-08-03, vor dem Merge.** Der Befund war richtig und wurde auf dem
> *Quellbranch* behoben (`8d9798d1e`), nicht erst hier — sonst wäre die Weitung mit dem Port
> nach `main` gewandert. `enable_sharepoint_import` fragt jetzt pro Backend, ob die Instanz
> einen Import überhaupt bedienen kann; `graph` verhält sich bitgenau wie vor dem Feature.
> Schritt 7 unten ist damit gegenstandslos. Live gegengeprüft am gemergten Baum:
> `SHAREPOINT_BACKEND=graph` ohne OneDrive → `enable_sharepoint_import = False`,
> `onprem` + Farm-URL → `True`. Der folgende Abschnitt beschreibt den Zustand *vor* dem Fix.


Die Probe hat den Gate-Wechsel in `KnowledgeBase.svelte` als „sauber gemergt" gemeldet und
der erste Entwurf hat ihn als reinen Fix verbucht. **Das ist zu kurz gegriffen.** Gemessen:

```python
# env.py (Fork)
SHAREPOINT_BACKEND = os.getenv("SHAREPOINT_BACKEND", "graph")     # nicht-leerer Default
# main.py (Fork), gemergt bei 2231
'enable_sharepoint_import': SHAREPOINT_BACKEND.strip() != '',      # ⇒ immer True
```

Das ersetzte Gate war `enable_onedrive_integration && enable_onedrive_business`, und
`ENABLE_ONEDRIVE_INTEGRATION` hat auf `main` den Default `'False'`. Bisher war der Eintrag
„Import from SharePoint" also überall dort unsichtbar, wo OneDrive nicht eingeschaltet war —
nach dem Port erscheint er **out of the box auf jeder Instanz**. Klickt ihn jemand ohne
Entra-App an, landet er in `_graph_backend` und bekommt
`401 No Microsoft OAuth session found`.

Auf 0.10.2 war das folgenlos, weil dieser Branch faktisch KHKI-Einzelbetrieb ist. `main` ist
die Basis für die Release-Branches, die Stadtbau und Falkensteg noch geschuldet sind
(CLAUDE.md §1) — dort ist es eine sichtbare UI-Änderung, die niemand abgenommen hat.

Erschwerend: Diese Weitung ist **absichtlich** und in
`test/sharepoint/test_sharepoint_backend_compat.py::TestSharePointPickerStaysVisibleOnGraph`
festgenagelt (`test_graph_default_still_shows_the_picker_without_any_onedrive_config`). Kein
automatischer Check wird sie je melden. Schritt 7 behandelt sie deshalb als Entscheidung,
nicht als Nebensatz.

---

## 4. Verhaltensänderungen, die mitfahren

Drei Änderungen im Merge sind korrekt, aber **außerhalb** des LDAP-/SharePoint-Features. Sie
gehören namentlich in die Commit-Nachricht und den PR-Text, damit sie ratifiziert und nicht
später entdeckt werden:

1. **`env.py`: `ENABLE_VERSION_UPDATE_CHECK` Default `'true'` → `'false'`.** Der Fork hört
   auf, gegen Upstream-Releases zu prüfen — für *jede* Installation, nicht nur KHKI. Herkunft:
   P3 in [`PLAN_SHAREPOINT_ONPREM_UI_GAPS.md`](PLAN_SHAREPOINT_ONPREM_UI_GAPS.md).
2. **`package.json`: `test:frontend` von `vitest` auf `vitest run --passWithNoTests`.**
   Watch-Modus → Einzellauf. Ändert CI-Verhalten für alle; vorher konnte die Suite „bestehen",
   indem sie hing.
3. **Das Picker-Gate aus §3.3.** Die größte der drei. Opt-out ist ein Einzeiler
   (`SHAREPOINT_BACKEND=''`), aber er muss pro Kunde gesetzt werden — solange Schritt 7 nicht
   anders entscheidet.

Abhängigkeiten: genau ein neuer Pin, `pyspnego==0.12.1`, in `backend/requirements.txt` und
`pyproject.toml`. Unkritisch, aber siehe Schritt 10 zur Falle.

---

## 5. Ablauf

Reihenfolge ist nicht beliebig: **das Backend landet und ist grün, bevor eine einzige
Svelte-Zeile angefasst wird.** Die Frontend-Hälften (Picker-Gate, Credential-Panel) sind ohne
die Backend-Flags `enable_sharepoint_import` / `enable_ldap_credential_store` bestenfalls
wirkungslos, schlimmstenfalls eine Regression — und diese Flags gibt es auf `main` nicht.

Schreibweisen unten sind Git-Bash (`Bash`-Werkzeug). Die Alembic-Schritte nutzen die
`VAR=… cmd`-Präfixform, die in PowerShell ein Parse-Fehler ist — **diese Schritte in
Git-Bash ausführen** oder vorher `$env:DATABASE_URL` setzen.

Ein Ablageort für Wegwerf-Datenbanken, einmal anlegen:
`mkdir -p /c/Users/neura/AppData/Local/Temp/owui-port`. Er wird unten überall als
Windows-Pfad geschrieben, weil `sqlite:////tmp/…` unter Git-Bash auf `C:\tmp\` zeigt,
`rm -f /tmp/…` aber auf `%LOCALAPPDATA%\Temp` — die Aufräumzeile träfe sonst eine andere
Datei als der Lauf. Gemessen: `cygpath -w /tmp` → `C:\Users\neura\AppData\Local\Temp`,
`python -c "os.path.abspath('/tmp')"` → `C:\tmp`.

---

### Schritt 1 — Worktree, Port-Branch, Frontend-Basislinie

Getrennter Arbeitsbaum, damit die geschützten Refs unangetastet bleiben.

```bash
git -C /c/Users/neura/Documents/Repositories/open-webui worktree add \
    /c/Users/neura/Documents/Repositories/owui-port-ldap-sp -b feature/ldap-sp-0.11.0 main
git -C /c/Users/neura/Documents/Repositories/open-webui branch -D probe/port-ldap-sp
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp && npm ci
npm run check 2>&1 | tee /c/Users/neura/AppData/Local/Temp/owui-port/check-baseline.txt
```

**Die Basislinie ist Pflicht und muss *hier* entstehen**, vor dem Merge. Schritt 12 vergleicht
gegen sie. Später ist sie nicht mehr zu bekommen: der Hauptcheckout steht auf dem Quellbranch
und darf nicht umgeschaltet werden, ein zweites `npm ci` wäre unnötige Wartezeit.

Fallen:

- `node_modules` ist **pro Worktree**, wird nicht geteilt. `npm ci` dauert; früh starten.
- Der Branch `probe/port-ldap-sp` ist ein Rest der Merge-Probe (Branches sind
  worktree-übergreifend). Er trägt keine Arbeit.
- `rerere` ist aktiv, hat bei der abgebrochenen Probe aber nur **Preimages** aufgezeichnet,
  keine Auflösungen. Der echte Merge fragt also ganz normal.
- Für das Backend ist kein venv nötig: das vorhandene Python hat `pyspnego 0.12.1` und den
  Rest installiert. Aber: **`python --version` → 3.13.1, `pyproject.toml` verlangt
  `>= 3.11, < 3.13.0a1`.** Der lokale Lauf ist damit kein Beweis für das Produktionsimage;
  entweder ein 3.11/3.12-venv anlegen oder den Vorbehalt in Schritt 16 notieren.

**done_when**

```bash
git -C /c/Users/neura/Documents/Repositories/owui-port-ldap-sp rev-parse --abbrev-ref HEAD   # feature/ldap-sp-0.11.0
git -C /c/Users/neura/Documents/Repositories/owui-port-ldap-sp log --oneline -1              # 73f5ab2f4
test -s /c/Users/neura/AppData/Local/Temp/owui-port/check-baseline.txt && echo BASELINE-OK
```

---

### Schritt 2 — Merge ausführen

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
git merge --no-commit --no-ff feature/ldap-sharepoint-credential
```

`--no-commit` ist nicht optional: die Favicons (Schritt 6) und der Alembic-Head-Split
(Schritt 8) müssen vor dem ersten Commit erledigt sein.

Weicht die Konfliktmenge von den drei erwarteten Dateien ab, haben sich die Branches seit der
Probe bewegt: **anhalten** und `git merge-base main feature/ldap-sharepoint-credential`
neu messen (war `f805abeee05f8899baf30d006abd964567d01198`).

**done_when**

```bash
git diff --name-only --diff-filter=U | sort
# backend/open_webui/main.py
# docs/FORK_CHANGES.md
# src/lib/i18n/locales/de-DE/translation.json
```

---

### Schritt 3 — `main.py` auflösen und die Fork-Haken nachweisen

Konflikt wie in §2.1: beide Zeilen behalten, `ENABLE_LDAP_CREDENTIAL_STORE` vor
`ENABLE_PLUGINS`, Marker weg.

Die naheliegende Fehlbedienung ist `--ours`: dann fehlt der Fork-Import und `main.py` wirft
später einen `NameError`. **`python -m py_compile` bemerkt das nicht** — es ist reine
Syntaxprüfung und löst keinen Namen auf. Der Grep auf die Feature-Schlüssel bemerkt es
ebenfalls nicht, weil er kleingeschrieben ist und der Import groß. Deshalb prüft `done_when`
den Import ausdrücklich und importiert das Modul wirklich.

`main.py` trägt außerdem vier Injektionen aus `FORK_CHANGES.md` §6, von denen eine
(`custom_css.router` **vor** `app.mount('/static', …)`) dokumentiert **still** ausfällt, wenn
sie verlorengeht. Der Merge erhält sie (in der Probe gemessen: alle vier vorhanden,
`custom_css.router` bei 813 vs. Mount bei 2851) — eine verrutschte Handauflösung nicht.
Deshalb laufen sie hier mit.

**done_when**

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
grep -cE '^(<<<<<<<|=======|>>>>>>>|\|\|\|\|\|\|\|)' backend/open_webui/main.py     # 0
grep -c '^    ENABLE_LDAP_CREDENTIAL_STORE,$' backend/open_webui/main.py           # 1
grep -c '^    SHAREPOINT_BACKEND,$'           backend/open_webui/main.py           # 1
grep -c 'enable_sharepoint_import\|enable_ldap_credential_store' backend/open_webui/main.py   # 2
# FORK_CHANGES §6, main.py:
grep -c '^    processing,$'            backend/open_webui/main.py                  # 1
grep -c 'processing.router'            backend/open_webui/main.py                  # 1
grep -c 'custom_css.router'            backend/open_webui/main.py                  # 1
grep -c 'onedrive.client_id_business'  backend/open_webui/main.py                  # 2
# Reihenfolge custom_css vor /static-Mount:
awk '/custom_css\.router/{a=NR} /app\.mount\("\/static"/{b=NR} END{print (a<b)?"ORDER-OK":"ORDER-BROKEN"}' backend/open_webui/main.py
# echter Import statt py_compile:
cd backend && WEBUI_SECRET_KEY=t python -c "import open_webui.main" && echo IMPORT-OK
git -C /c/Users/neura/Documents/Repositories/owui-port-ldap-sp status --porcelain backend/open_webui/static/   # leer (sonst Schritt 6 wiederholen)
```

---

### Schritt 4 — `de-DE/translation.json` auflösen

Alle Zeilen beider Seiten behalten, alphabetisch: `Credential storage…` vor
`Credential used…`, `Last run` vor `Last used`.

Nur `de-DE` trägt die Texte; die übrigen 62 Locales fallen auf den englischen
Schlüsseltext zurück, und der *ist* die beabsichtigte englische Fassung. Ein
`npm run i18n:parse` würde alle 63 Dateien anfassen und gehört in einen eigenen Commit.

Zwei Fehlbedienungen, die der naive Check nicht sieht:

- **`--theirs`** behält alle sechs Fork-Schlüssel, das JSON bleibt gültig — und die drei
  0.11-Labels (`Credential used for Document Intelligence.`,
  `Credentials used to authenticate with the Jupyter server.`, `Last run`) sind weg. Sie
  erscheinen dann auf Deutsch unübersetzt.
- Eine zu weit gefasste Auswahl beim Handedit kann die bestehende i18n-Injektion aus
  `FORK_CHANGES.md` (Force-Retrieval-Schlüssel, `de-DE` Zeile 1273 auf `main`) mitreißen.

**done_when**

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
python -c "import json;json.load(open('src/lib/i18n/locales/de-DE/translation.json',encoding='utf-8'));print('JSON-OK')"
grep -c '"Stored network password"\|"Allow storing my password"\|"Delete stored password"\|"No password is stored."\|"Credential storage turned off\|"Last used"' \
     src/lib/i18n/locales/de-DE/translation.json          # 6  (Fork)
grep -c '"Credential used for Document Intelligence."\|"Credentials used to authenticate with the Jupyter server."\|"Last run"' \
     src/lib/i18n/locales/de-DE/translation.json          # 3  (0.11)
grep -c 'Force knowledge retrieval on native tool calling' \
     src/lib/i18n/locales/de-DE/translation.json src/lib/i18n/locales/en-US/translation.json   # je 1
```

---

### Schritt 5 — `docs/FORK_CHANGES.md` vorläufig freiräumen

```bash
git checkout --ours docs/FORK_CHANGES.md && git add docs/FORK_CHANGES.md
```

HEAD ist das 0.11.0-Inventar; die Fork-Zeilen werden in Schritt 15 geschrieben, nicht hier
von Hand gemergt. `--theirs` wäre falsch — die Fork-Seite setzt die 0.11.0-Formulierungen für
`retrieval/models.py`, `RagSettingsModal.svelte` und das `+N / −N`-Format der Overlay-Tabelle
zurück. Die Testzahlen beider Seiten (HEAD „329 grün", Fork „321 / 110 sharepoint") sind nach
diesem Merge **beide** veraltet; sie werden in Schritt 15 aus dem echten Lauf von Schritt 11
neu geschrieben, nicht addiert.

**done_when**

```bash
grep -cE '^(<<<<<<<|=======|>>>>>>>)' docs/FORK_CHANGES.md   # 0
git diff --name-only --diff-filter=U                        # leer
```

---

### Schritt 6 — Favicons zurücknehmen (stille Gefahr 1)

```bash
git checkout HEAD -- backend/open_webui/static/favicon.ico backend/open_webui/static/favicon.png
```

Begründung in §3.2. Ab hier gilt für den gesamten Port: **kein `git add -A`**, immer
explizite Pfade.

**done_when**

```bash
git diff HEAD --stat -- backend/open_webui/static/                     # leer
git rev-parse :backend/open_webui/static/favicon.ico                   # 14c5f9c6d437ed109a8579031cf181ee52bdf30e
```

---

### Schritt 7 — ~~Picker-Gate~~ entfällt (auf dem Quellbranch behoben, siehe §3.3)

Aus §3.3. Zwei gangbare Wege; **beide brauchen menschliche Zustimmung, bevor der PR nach
`main` geht.**

**Weg A (empfohlen) — Flag am Backend-Modus statt an einem Default-String festmachen.**
In `main.py`:

```python
'enable_sharepoint_import': SHAREPOINT_BACKEND.strip().lower() == 'onprem'
                           or (config.get('onedrive.enable') and ENABLE_ONEDRIVE_BUSINESS),
```

Damit bleibt der On-Prem-Pfad ohne jede Entra-Variable erreichbar (das war der Sinn von P1),
und Graph-Instanzen sehen den Picker exakt unter den Bedingungen, unter denen sie ihn heute
sehen. Preis: `TestSharePointPickerStaysVisibleOnGraph::test_graph_default_still_shows_the_picker_without_any_onedrive_config`
muss umgeschrieben werden — dieser Test nagelt die Weitung fest, er ist kein
Rückwärtskompatibilitäts-Test.

**Weg B — so lassen, ausdrücklich ratifizieren.** Dann gehört in den PR-Text: „der
SharePoint-Eintrag erscheint ab jetzt auf jeder Instanz; Opt-out ist `SHAREPOINT_BACKEND=''`",
und die Release-Branches für Stadtbau und Falkensteg müssen die Variable setzen.

Was in beiden Fällen **nicht** getan wird: `ONEDRIVE_CLIENT_ID` mit einem Platzhalter füllen,
um das alte Gate zu öffnen (schaltet die OneDrive-Einträge mit, die dann ins Leere laufen).

**done_when** — bei Weg A:

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp/backend
# Positivfall on-prem:
WEBUI_SECRET_KEY=t SHAREPOINT_BACKEND=onprem python -c "..."   # features.enable_sharepoint_import == True
# Negativfall: kein SHAREPOINT_BACKEND, kein OneDrive:
WEBUI_SECRET_KEY=t python -c "..."                              # features.enable_sharepoint_import == False
```

(Beides wird in Schritt 14 zusätzlich am laufenden Server gegen `/api/config` geprüft — der
Python-Aufruf hier ist die schnelle Vorabprobe.) Bei Weg B: schriftliche Zustimmung im PR,
sonst nichts zu tun.

---

### Schritt 8 — Alembic-Merge-Revision (stille Gefahr 2)

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp/backend/open_webui
alembic heads          # erwartet ZWEI: ad192b50687b und e7f8a9b0c1d2
alembic merge -m "merge ldap credential store" e7f8a9b0c1d2 ad192b50687b
```

Die erzeugte Datei wird **unverändert** committet (leere `upgrade()`/`downgrade()`), und die
neue Revisions-ID wird notiert — Schritt 9 vergleicht gegen sie.

Verboten, mit Begründung:

- **`e7f8a9b0c1d2.down_revision` auf `ad192b50687b` umhängen.** Diese Revision ist in der
  produktiven KHKI-Datenbank gestempelt. Nach dem Umhängen hielte Alembic diese Datenbank für
  bereits am Head und würde **jede** 0.11-Migration zwischen `e48721182479` und
  `ad192b50687b` still überspringen. Das ist wörtlich der Vorfall in
  [`ALEMBIC_MERGE_PLAYBOOK.md`](ALEMBIC_MERGE_PLAYBOOK.md) §2, untersagt durch Regel 2 und §8.
- **Reparaturmigration** jeder Art, insbesondere das `c7d8e9f0…_repair_custom_schema`-Muster
  (CLAUDE.md §4).
- **Die Merge-Datei von Hand schreiben.** Sie muss aus einem echten `alembic merge` stammen,
  sonst droht eine doppelte Revisions-ID (Playbook §9).

**done_when**

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp/backend/open_webui
alembic heads | wc -l                                                     # 1
D=C:/Users/neura/AppData/Local/Temp/owui-port/fresh.db; rm -f "$D"
DATABASE_URL="sqlite:///$D" alembic upgrade head                          # exit 0
python -c "import sqlite3;print([r[0] for r in sqlite3.connect(r'C:/Users/neura/AppData/Local/Temp/owui-port/fresh.db').execute(\"select name from sqlite_master where type='table' and name='user_credential'\")])"
# ['user_credential']
```

---

### Schritt 9 — Den KHKI-förmigen Upgrade-Pfad beweisen

Ein Lauf gegen eine leere Datenbank kann eine falsche Elternschaft **nicht** entdecken: dort
wird jede Revision besucht, egal wie der DAG aussieht. Dieser Schritt ist der einzige, der es
kann — aber nur, wenn er richtig gebaut ist.

**Die Datenbank darf nicht von Hand fabriziert werden.** Eine Datei, die nur eine
`alembic_version`-Zeile enthält, scheitert unterwegs an `856c5b02fb54`
(`op.add_column('chat_message', …)`, ohne Inspector-Guard) mit
`OperationalError: no such table: chat_message`. Die Prüfung ginge dann aus einem Grund rot,
der nichts mit dem Port zu tun hat — und würde beim ersten Mal gelöscht statt verstanden.
Stattdessen wird der KHKI-Zustand **erzeugt**:

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp/backend/open_webui
D=C:/Users/neura/AppData/Local/Temp/owui-port/khki-shape.db; rm -f "$D"
DATABASE_URL="sqlite:///$D" alembic upgrade e7f8a9b0c1d2   # baut das echte 0.10.2-Schema bis zur Fork-Revision
DATABASE_URL="sqlite:///$D" alembic upgrade head           # die 8 Delta-Revisionen + Merge-Head
```

Ebenso wenig taugt `alembic current | grep -q "(head)"` als Beweis: bei umgehängter
Elternschaft wäre `e7f8a9b0c1d2` selbst der einzige Head, `upgrade head` ein No-op mit Exit 0
und `current` würde `e7f8a9b0c1d2 (head)` drucken — der Grep ginge grün, ohne dass eine
einzige 0.11-Migration gelaufen wäre. Deshalb wird auf **Identität** und auf ein
**0.11-eigenes Artefakt** geprüft: Spalte `variables` an Tabelle `user` aus `b0018471bbbe`.

**done_when**

```bash
DATABASE_URL="sqlite:///$D" alembic current    # exakt die in Schritt 8 notierte Merge-Revision
python - <<'PY'
import sqlite3
c = sqlite3.connect(r'C:/Users/neura/AppData/Local/Temp/owui-port/khki-shape.db')
cols = [r[1] for r in c.execute('PRAGMA table_info(user)')]
tabs = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
assert 'variables' in cols, '0.11-Migration b0018471bbbe ist NICHT gelaufen'
assert 'user_credential' in tabs
print('KHKI-PATH-OK')
PY
```

**Ehrlich dazu:** Dass die KHKI-Produktivdatenbank wirklich auf `e7f8a9b0c1d2` steht, ist aus
„produktiv bei KHKI" und [`LDAP_SHAREPOINT_BACKEND.md`](LDAP_SHAREPOINT_BACKEND.md)
**abgeleitet, nicht gemessen** — den Cluster hat niemand abgefragt. Die Merge-Revision ist
davon unabhängig richtig (zwei Heads sind eine Tatsache ohne KHKI); nur die Schwere der
Umhäng-Gefahr hängt an der Antwort.

---

### Schritt 10 — Abhängigkeiten prüfen

`pyspnego==0.12.1` muss in **beiden** Dateien stehen: `backend/requirements.txt` (Block
`## LDAP`, nach `ldap3==2.9.1`) und `pyproject.toml`.

Die Falle: `pyspnego 0.12.1` ist im vorhandenen Python bereits installiert. Die Backend-Suite
in Schritt 11 wird also **auch dann grün**, wenn die Requirement-Zeilen verlorengingen. Ein
grüner Lauf ist hier kein Beleg — nur der Grep ist einer.

Zweite Falle: `pyspnego` zieht `sspilib` ausschließlich unter Windows (Environment-Marker).
Ein direkter `sspilib`-Import liefe lokal durch und stürzte im Linux-Container ab. Heute
importiert `sharepoint_onprem_client.py` nur `spnego` — das muss so bleiben.

**done_when**

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
grep -c 'pyspnego==0.12.1' backend/requirements.txt pyproject.toml    # je 1
grep -rn 'sspilib' backend/open_webui/                                # keine Treffer
python -c "import spnego; print('spnego-OK')"
```

---

### Schritt 11 — Backend-Suiten (Tor zum Frontend)

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp/backend
WEBUI_SECRET_KEY=t python -m pytest open_webui/test/sharepoint/ -q          # 110 passed
WEBUI_SECRET_KEY=t python -m pytest open_webui/test/test_user_credentials.py -q   # 23 passed
WEBUI_SECRET_KEY=t python -m pytest open_webui/test/custom_css/ -q          # explizit, nicht implizit
WEBUI_SECRET_KEY=t python -m pytest open_webui/test/ -q                     # Gesamtzahl notieren
```

Die 110 setzen sich aus 16 (`backend_compat`) + 6 (`import_onprem`) + 24 (`onprem_client`) +
39 (`import`) + 25 (`graph_client`) zusammen — per `grep -cE '^\s*(async )?def test_'` je Datei
gezählt. **Auf Zahlen prüfen, nicht auf „0 failed":** pytest druckt bei Erfolg „N passed", die
Zeichenkette „0 failed" erscheint nie, und ein Sammelfehler heißt „errors", nicht „failed".

`test/custom_css/` gibt es nur auf `main`; der Quellbranch kennt das Paket nicht. Der Merge
behält es — deshalb hier ausdrücklich aufrufen statt sich auf die Gesamtsammlung zu verlassen.

Weitere Fallen:

- `WEBUI_SECRET_KEY` muss gesetzt sein, sonst wirft `env.py` beim Import ein `SystemExit`.
- Hängt pytest bei 100 % in `threading._shutdown()`, ist die neue `test/conftest.py` nicht
  gelandet (aiosqlite-Verbindungs-Worker, nicht als Daemon).
- **Nach jedem Lauf** `backend/open_webui/static/` prüfen (§3.2).
- Der Lauf findet auf Python 3.13.1 statt, `pyproject.toml` verlangt `< 3.13.0a1`. Wenn kein
  3.11/3.12-venv gebaut wird, gehört dieser Vorbehalt in die Commit-Nachricht: der eigentliche
  Nachweis ist dann CI auf dem unterstützten Interpreter.

**Zusätzlich, weil bisher nur mit Mocks geprüft wurde:** Der Importpfad verlinkt und verarbeitet
jede Datei zweimal. `_import_single_graph_file` ruft `upload_file_handler(..., metadata={'knowledge_id': …}, process=True, …)` **und** danach `process_file(...)` + `Knowledges.add_file_to_knowledge_by_id(...)`;
`routers/files.py` (0.11, Zeilen 213–258) verlinkt inzwischen selbst auf
`file_metadata['knowledge_id']` und verarbeitet ebenfalls. `models/knowledge.py` hat einen
`UniqueConstraint('knowledge_id','file_id')`, und `add_file_to_knowledge_by_id` schluckt den
resultierenden `IntegrityError` in einem nackten `except Exception: return None` **nach** einem
`await db.commit()` — die geteilte Session braucht danach ein Rollback. Das ist vorbestehend
(an der Merge-Basis identisch) und wird in diesem Port **nicht** repariert, aber es soll
gemessen statt geerbt werden: zwei Dateien in eine Wissensdatenbank importieren, genau zwei
`knowledge_file`-Zeilen erwarten, keinen `PendingRollbackError`. Reproduziert es, wird
`knowledge_id` aus den `upload_file_handler`-Metadaten entfernt (der explizite Fork-Link bleibt)
und der Befund in Schritt 15 als Folgearbeit notiert.

**done_when** — die vier Zahlen oben treffen zu, Exit-Code 0, und:

```bash
git -C /c/Users/neura/Documents/Repositories/owui-port-ldap-sp status --porcelain backend/open_webui/static/   # leer
```

---

### Schritt 12 — Frontend gegen den gemergten (noch nicht restylten) Baum

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
grep -q '"test:frontend": "vitest run --passWithNoTests"' package.json && echo SCRIPT-OK
npx vitest run src/lib/utils/onedrive-file-picker.test.ts     # 11 passed
npm run test:frontend                                          # 13 passed gesamt
npm run check 2>&1 | tee /c/Users/neura/AppData/Local/Temp/owui-port/check-after.txt
diff /c/Users/neura/AppData/Local/Temp/owui-port/check-baseline.txt \
     /c/Users/neura/AppData/Local/Temp/owui-port/check-after.txt
npm run build
```

Zu den Zahlen: `onedrive-file-picker.test.ts` enthält **11** `it(`-Blöcke (gezählt, nicht
geschätzt — eine frühere Angabe von 13 ist falsch). `main` bringt zusätzlich
`src/lib/shortcuts.test.ts` mit 2 Tests mit, den der Quellbranch nicht kennt; die
Gesamtsumme im gemergten Baum ist deshalb **13**, nicht 11. `shortcuts.ts` braucht kein DOM
(einziger Global-Zugriff: `typeof navigator !== 'undefined'`).

Das ist der erste echte Frontend-Beleg auf 0.11: vorher war die Suite mangels DOM-Umgebung rot
(`UPSTREAM_0.11.0_TRIAGE.md` §5.3, „window is not defined"), der Fork bringt den
`vi.stubGlobal('window', { location: { origin: 'http://localhost:5173' } })`-Stub mit.

Grün heißt hier **nicht**, dass die Credential-Oberfläche geprüft ist — für sie existiert kein
einziger Test. Und der Gate-Grep muss beidseitig sein: ein zusätzlich eingefügtes
`enable_sharepoint_import` neben der alten OneDrive-Konjunktion liefert ebenfalls genau einen
Treffer, während der Picker on-prem weiter unsichtbar bliebe.

**done_when**

```bash
grep -c 'enable_sharepoint_import'  src/lib/components/workspace/Knowledge/KnowledgeBase.svelte   # 1
grep -c 'enable_onedrive_business'  src/lib/components/workspace/Knowledge/KnowledgeBase.svelte   # 0
# npm run build: exit 0; check-after zeigt keine NEUEN Fehler gegenüber check-baseline
```

---

### Schritt 13 — `CredentialStore.svelte` + Einhängung auf die 0.11-Formsprache umstellen

Der `<script>`-Block wird **wörtlich** übernommen — null Logikänderung. Umgestellt werden rund
30 Markup-Zeilen, Vorbild ist der direkte Nachbar `UpdatePassword.svelte`, den 0.11 umgebaut hat:

| Stelle | 0.10.2 (Fork) | 0.11 |
|---|---|---|
| Kopfzeile | `flex justify-between items-center text-sm`, Label `font-medium` | `flex items-center justify-between gap-2.5`, Label `text-xs text-gray-600 dark:text-gray-400` |
| Aktionsknopf | handgeschriebene Klassen | lokale Konstante `actionButtonClass = 'text-xs text-gray-500 transition-colors hover:text-gray-900 dark:text-gray-500 dark:hover:text-white'` |
| Erklärtext | im `{#if show}`-Rumpf vergraben | `<p class="mt-0.5 text-[0.6875rem] text-gray-400 dark:text-gray-600">` unter der Kopfzeile |
| „Passwort löschen" | schwarze Pille | `class={actionButtonClass}` |
| Label + Switch | freies `div`-Paar | `<UserSettingRow>` mit `slot="label"`, Switch als Default-Slot (Muster: `Personalization.svelte:117-144`) |

In `Account.svelte` ersetzt `<UserSettingSection title={$i18n.t('Stored network password')}>`
den rohen `<div class="mt-2">`-Wrapper, platziert zwischen dem schließenden `{/if}` des
Passwort-Abschnitts und dem `{#if}` der API-Schlüssel.

- Gate `{#if $config?.features?.enable_ldap_credential_store}` bleibt.
- Der Rumpf-Wrapper `{#if show}<div class="py-2.5 space-y-2.5">` bleibt — den hat 0.11 nicht
  angefasst.
- **`src/lib/components/common/Switch.svelte` nicht mitportieren.** Der `<script>`-Block ist auf
  beiden Branches byte-identisch, nur die Tailwind-Klassen haben sich geändert; portieren würde
  das 0.11-Restyling zurücknehmen. `on:change={(e) => optInHandler(e.detail)}` funktioniert
  wörtlich gegen die Fassung auf `main`.

Das ist die einzige Gestaltungsarbeit im Port und **für jede automatische Prüfung unsichtbar**:
es kompiliert, es rendert, die Tests bleiben grün — und es sieht aus wie eine 0.10.2-Insel.

**done_when**

```bash
grep -c 'UserSettingSection\|UserSettingRow' src/lib/components/chat/Settings/Account/CredentialStore.svelte   # >= 2
grep -c 'class="mt-2"' src/lib/components/chat/Settings/Account.svelte                                         # 0
npm run check && npm run build && npm run test:frontend                                                        # 13 passed
```

Dazu die Sichtprüfung in Schritt 14 — das Panel rendert nur bei gesetztem
`ENABLE_LDAP_CREDENTIAL_STORE`; ohne diese Variable schaut man auf einen leeren Reiter und
hält ihn für fertig.

---

### Schritt 14 — Laufender Nachweis am eigenen Build

Bis hierher hat niemand die Anwendung gestartet. `PLAN_SHAREPOINT_ONPREM_UI_GAPS.md` sagt dazu
unmissverständlich: „Erst der laufende Pod belegt, dass der Picker erscheint; bis dahin ist P1
‚umgesetzt', nicht ‚bestätigt'." KHKI fährt 0.10.2 und kann für diesen Port **nicht** als
Nachweisinstanz dienen — ein lokaler 0.11-Start ist der einzige verfügbare Beleg. Ablauf für
eine spätere Instanz: [`PLAYWRIGHT_DEPLOY_SMOKE_PROTOCOL.md`](PLAYWRIGHT_DEPLOY_SMOKE_PROTOCOL.md).

Vier Aussagen, jeweils Backend starten und `GET /api/config` lesen, dann die Oberfläche
ansehen:

| Umgebung | `features.enable_sharepoint_import` | UI |
|---|---|---|
| `SHAREPOINT_BACKEND=onprem`, keine Entra-Variablen | `true` | SharePoint-Eintrag im „Inhalt hinzufügen"-Menü sichtbar |
| `SHAREPOINT_BACKEND=''`, OneDrive aus | `false` | Eintrag weg, OneDrive-Einträge unverändert |
| `ENABLE_LDAP_CREDENTIAL_STORE=true` | `enable_ldap_credential_store: true` | Panel in Einstellungen → Konto sichtbar |
| Variable nicht gesetzt | `false` | Panel nicht vorhanden |

Bei Weg A aus Schritt 7 kommt eine fünfte hinzu: Default-Umgebung (nichts gesetzt) →
`enable_sharepoint_import` ist `false`, also gleich wie `enable_onedrive_business` heute.

**done_when** — alle Zeilen der Tabelle beobachtet und im Commit-Text bzw. PR notiert; bei
Abweichung ist Schritt 7 oder 13 nicht fertig.

---

### Schritt 15 — `FORK_CHANGES.md` neu erzeugen und **alle** Detektoren laufen lassen

Auf dem 0.11.0-Inventar aus Schritt 5 aufsetzen und ergänzen:

- **Additive Backend:** `utils/sharepoint_backend.py`, `utils/sharepoint_onprem_client.py`,
  `models/user_credentials.py`, Migration `e7f8a9b0c1d2` + die neue Merge-Revision.
- **Additive Frontend:** `Settings/Account/CredentialStore.svelte`.
- **Injection:** `KnowledgeBase.svelte` (`enable_sharepoint_import`), `apis/users/index.ts`,
  `Settings/Account.svelte`, `routers/auths.py` (`maybe_store_ldap_credential`), `main.py`
  (2 Env-Importe + 2 Feature-Schlüssel), `middleware.py` (`__sharepoint__` an 2 der 3
  `extra_params`-Stellen).
- **Overlay:** `knowledge.py` („backend-agnostisch seit 2026-07-31"), `env.py`
  (`ENABLE_VERSION_UPDATE_CHECK=false`).
- **Tests:** Zahlen aus dem echten Lauf von Schritt 11, plus die zwei Betriebsnotizen
  (`conftest.py`/aiosqlite-Hänger, `WEBUI_SECRET_KEY`-`SystemExit` beim Import).
- Die Zeile zu `onedrive-file-picker.test.ts` von „currently red" auf „repariert" umschreiben.

**Zwei Detektor-Korrekturen — und eine Warnung vor einer falschen.** Ein früherer Entwurf sah
vor, den `env.py`-Detektor auf „nur `FORK_VERSION_SUFFIX`" einzudampfen. Das ist zweifach
falsch und würde genau den Schutz entfernen, dessentwegen diese Datei existiert. Gemessen auf
`main`:

```
git show main:backend/open_webui/env.py | grep -nE "FORK_VERSION_SUFFIX|EMBEDDING_RETRY_|GRAPH_|SHAREPOINT_"
148-151  FORK_VERSION_SUFFIX
712-714  EMBEDDING_RETRY_INITIAL_DELAY / _MAX_DELAY / _BACKOFF_FACTOR
```

Also: `EMBEDDING_RETRY_*` lebt sehr wohl in `env.py` (es trägt das Embedding-Retry-Overlay),
und nach *diesem* Port kommen `SHAREPOINT_BACKEND`, `SHAREPOINT_ONPREM_SITE_URL`,
`SHAREPOINT_ONPREM_VERIFY_TLS` dazu. Einzig `GRAPH_` ist tatsächlich tot (0 Treffer). Der
Detektor wird deshalb **erweitert, nicht verkleinert**:

```bash
grep -nE "FORK_VERSION_SUFFIX|EMBEDDING_RETRY_|SHAREPOINT_|LDAP_|ENABLE_VERSION_UPDATE_CHECK" backend/open_webui/env.py
```

Denn sonst landen vier neue Fork-Haken **ohne jeden Detektor** auf `main`:
`ENABLE_LDAP_CREDENTIAL_STORE`, `LDAP_CREDENTIAL_ENCRYPTION_KEY`, `LDAP_CREDENTIAL_TTL`,
`LDAP_NETBIOS_DOMAIN`. `LDAP_CREDENTIAL_ENCRYPTION_KEY` hat bewusst **keinen**
`WEBUI_SECRET_KEY`-Rückfall — geht sie verloren, fällt der Credential-Store bei KHKI hart aus.
Ein Haken ohne Detektor ist ein Haken, der beim nächsten Upstream-Sprung verschwindet und
dabei niemanden weckt.

Zweite Korrektur: der `middleware.py`-Detektor steht auf „(expect 7)". Gemessen —
`main` 7, Quellbranch 8, Merge-Basis 6, gemergter Baum **9** (die zwei neuen bei ~2474 und
~3861, „a ready SharePoint client for on-prem deployments"). Die Zeile muss auf
„(expect 9: 1 blank-query, 2 per-level RAG, 3 KB-deterministic-inject, 1 pyodide,
2 sharepoint)" und die Diff-Angabe `+107 / −24` mitgezogen werden. Auf der Datei mit der
höchsten Änderungsrate im Repo ist eine stehengebliebene 7 die Einladung, beim nächsten Bump
genau die zwei neuen Marker zu verlieren und den Detektor trotzdem für korrekt zu halten.

Ebenfalls neu in §6 aufnehmen (nicht nur als `done_when` in Schritt 3):
`grep -n "enable_ldap_credential_store\|enable_sharepoint_import" backend/open_webui/main.py`
(expect 2).

Weiter zu pflegen: In [`PLAN_SHAREPOINT_ONPREM_UI_GAPS.md`](PLAN_SHAREPOINT_ONPREM_UI_GAPS.md)
P1 als durch `2530e5602` geschlossen markieren und die Restpunkte gegen 0.11 gegenprüfen; in
[`LDAP_SHAREPOINT_BACKEND.md`](LDAP_SHAREPOINT_BACKEND.md) die Version auf 0.11.0 setzen und
die Migrationskette über die neue Merge-Revision beschreiben. `docs/` **nie** pauschal
auschecken (§6).

**done_when** — die Detektoren sind keine Prosa, sondern ein Lauf. Alle Greps aus §5 bis §8 von
`FORK_CHANGES.md` in ein Skript legen, jeden ausführen und Ist gegen Soll protokollieren; das
Protokoll gehört in die Commit-Nachricht. Gemessene Basislinien zum Abgleich:

| Detektor | Soll |
|---|---|
| `grep -c '# FORK:' backend/open_webui/utils/middleware.py` | 9 |
| `grep -c '# FORK:' backend/open_webui/config.py` | 5 |
| `git ls-tree --name-only HEAD .github/workflows/ \| grep -v '\.disabled$'` | nur `azure-acr-build.yaml` |
| `grep -c 'sharepoint_backend.py\|sharepoint_onprem_client.py\|user_credentials.py\|e7f8a9b0c1d2\|CredentialStore.svelte\|pyspnego' docs/FORK_CHANGES.md` | >= 6 |
| `grep -c '__sharepoint__' backend/open_webui/utils/middleware.py` | 2 |
| `grep -q 'maybe_store_ldap_credential' backend/open_webui/routers/auths.py` | Treffer |
| `grep -n 'ENABLE_VERSION_UPDATE_CHECK' backend/open_webui/env.py \| grep "'false'"` | Treffer |

---

### Schritt 16 — Explizit stagen, committen, pushen

1. Favicon-Prüfung aus Schritt 6 ein letztes Mal (die Testläufe haben `static/` erneut
   angefasst).
2. **Datei für Datei stagen, niemals `git add -A`.**
3. Commit-Nachricht enthält: `alembic current` und `alembic heads` vor und nach dem Merge
   (Playbook Regel 6), das Detektor-Protokoll aus Schritt 15, die Testzahlen aus Schritt 11/12,
   die drei Verhaltensänderungen aus §4 samt getroffener Entscheidung zu Schritt 7, und den
   Vorbehalt zum Python-Interpreter aus Schritt 1.
4. Auf `neurawork` als **neuen** Branch pushen, PR gegen `main`. `main` lokal nicht
   fast-forwarden.

Frontend- und Backend-Hälfte müssen in **einem** Commit/PR liegen: das Gate in
`KnowledgeBase.svelte` liest `enable_sharepoint_import`, das Panel in `Account.svelte`
`enable_ldap_credential_store` — getrennt ausgeliefert bekommt man entweder ein unsichtbares
Panel oder einen verschwundenen SharePoint-Picker.

**done_when**

```bash
cd /c/Users/neura/Documents/Repositories/owui-port-ldap-sp
git status --porcelain                                  # leer
git log --oneline -1                                    # der Merge-Commit
git diff --stat main HEAD -- backend/open_webui/static/ # leer
git -C /c/Users/neura/Documents/Repositories/open-webui reflog show main -n 3   # kein Eintrag aus dieser Sitzung
git push neurawork HEAD:feature/ldap-sp-0.11.0
```

---

## 6. Was nicht portiert wird

**`backend/open_webui/static/favicon.ico` / `favicon.png` — harter Ausschluss.**
Sie mergen sauber, es gibt keinen Konflikt und keine Warnung; nichts fragt je nach. Messwerte
und Begründung in §3.2: der Quellbranch trägt die Upstream-Stock-Icons, `main` das
Fork-Branding — der Port würde es löschen. Folge: `git add -A` ist für den gesamten Port
verboten, und die Prüfung läuft nach jedem Backend-Lauf erneut.

**Das Umhängen von `e7f8a9b0c1d2.down_revision`.** Verboten nach
[`ALEMBIC_MERGE_PLAYBOOK.md`](ALEMBIC_MERGE_PLAYBOOK.md) Regel 2 / §8; §2 dokumentiert den
Vorfall. Stattdessen `alembic merge` (Schritt 8).

**Reparaturmigrationen jeder Art**, kein `c7d8e9f0…_repair_custom_schema`-Muster, kein
`alembic stamp` gegen eine produktive Datenbank (CLAUDE.md §4). Die erzeugte Merge-Revision
behält leere `upgrade()`/`downgrade()` und wird nicht von Hand bearbeitet.

**`backend/open_webui/migrations/env.py`.** Der Diff `main` ↔ Quellbranch besteht
ausschließlich aus Upstream-Zusätzen auf `main` (Importe von `ChatMessage` und `Chat`); der
Port fasst die Datei nicht an. *Vorbestehend und außerhalb des Zuschnitts:* keiner der beiden
Branches importiert dort `UserCredential`, ein künftiges
`alembic revision --autogenerate` sähe `user_credential` also als unbekannt. Die
Fork-Migration ist handgeschrieben, für den Port folgenlos.

**`backend/open_webui/migrations/_fork_helpers.py`.** Auf `main` bereits vorhanden und
byte-identisch zum Quellbranch; beide von der Fork-Migration importierten Helfer
(`create_table_if_missing`, `drop_table_if_exists`) lösen unverändert auf.

**`src/lib/components/common/Switch.svelte`.** `<script>` byte-identisch auf beiden Branches,
geändert haben sich nur Tailwind-Klassen. Portieren würde das 0.11-Restyling zurücknehmen.

**`docs/` pauschal.** Kein `git checkout feature/ldap-sharepoint-credential -- docs/`, kein
zweigweiter Doku-Diff: der Quellbranch kennt `docs/CUSTOM_CSS.md` und
`docs/UPSTREAM_0.11.0_TRIAGE.md` nicht — beides gäbe es danach nicht mehr. Dieselbe
Gefahrenklasse wie bei den Migrationen (§1).

**`docs/FORK_CHANGES.md` von einer der beiden Seiten als Endzustand.** `--ours` ist nur die
Zwischenlösung aus Schritt 5.

**Die Suche nach dem verwaisten Alembic-Head `a2b3c4d5e6f7` auf `main`.** Gemessen falsch: alle
64 Revisionsdateien geparst, genau ein Head (`ad192b50687b`), null hängende
`down_revision`-Verweise. Keine Zeit darauf verwenden.

**Jeder Commit, Push, Reset oder Rebase auf `main` oder `feature/ldap-sharepoint-credential`.**
Die gesamte Arbeit findet im neuen Worktree statt; `main` bewegt sich nur über den PR. Der
Hauptcheckout steht derzeit auf dem Quellbranch — nicht umschalten. Der Restbranch
`probe/port-ldap-sp` aus der Merge-Probe darf gelöscht werden.

---

## 7. Was offen ist

**Soll KHKI überhaupt auf 0.11.0?** Die Instanz fährt 0.10.2 on-prem mit dem Feature
produktiv. Dieser Port macht das Feature auf 0.11.0 verfügbar — ob, wann und in welche
Richtung KHKI wechselt, steht nirgends. Die Alternative wäre ein Rückport auf einen
0.10.2-Release-Branch für diesen Kunden. Die Antwort verschiebt die Dringlichkeit des ganzen
Vorhabens und das Gewicht von Schritt 9.

**Was steht wirklich in `alembic_version` der KHKI-Produktivdatenbank?** Niemand hat den
Cluster abgefragt (siehe Schritt 9). Die Merge-Revision ist unabhängig davon richtig; die
Einstufung der Umhäng-Gefahr und die Frage, ob Schritt 9 gegen einen echten Dump geprobt
werden muss, hängen daran.

**Picker-Gate: Weg A oder Weg B?** Schritt 7. Das ist die einzige Stelle im Port, an der eine
sichtbare UI-Änderung Kunden trifft, die mit dem Feature nichts zu tun haben. Weg A kostet
einen umgeschriebenen Test, Weg B kostet eine Umgebungsvariable pro Kunde und eine bewusste
Zusage.

**Werden die beiden anderen Mitfahrer ratifiziert oder abgetrennt?**
`ENABLE_VERSION_UPDATE_CHECK` auf `false` schaltet die Upstream-Prüfung für **jede**
Installation ab, nicht nur KHKI; `test:frontend` auf `vitest run` ändert CI-Verhalten für alle.
Beide sind in der Sache richtig, beide liegen außerhalb des Features, und beides ist keine
Entscheidung, die das Repo für euch treffen kann.

**Welcher Branch ist das echte Ziel?** `main` steht auf 0.11.0 und ist gepusht, aber CLAUDE.md
§1 beschreibt die 0.11.0-Arbeit weiterhin als auf dem ungepushten `feature/owui-0.11.0`
liegend und nennt Release-Branches für Stadtbau und Falkensteg als vorrangig. Ob dieser Port
jetzt als PR nach `main` geht, hinter diesen Release-Branches wartet oder auf einen
Kundenbranch wandert, ist eine Liefer-Entscheidung, keine Repo-Tatsache. CLAUDE.md §1 und
`PLAN_SHAREPOINT_ONPREM_UI_GAPS.md` P4 sind an dieser Stelle beide veraltet und gehören beim
nächsten Anfassen mitkorrigiert.

---

## 8. Aufwand

**3–5 Stunden**, eine Person, ein Zug, sofern sich der Merge so verhält wie gemessen.

| Block | Zeit |
|---|---|
| Worktree, `npm ci`, `check`-Basislinie | ~20 min (überwiegend Warten) |
| Merge + alle drei Konflikte | ~15 min (drei Zeilen echter Code, Basisseite leer) |
| Favicons | ~2 min |
| Picker-Gate-Entscheidung + Umsetzung | ~20 min (Weg A inkl. Testanpassung), Weg B ~0 |
| Alembic-Merge + **beide** Nachweispfade | 30–45 min |
| Backend-Suiten | ~15 min, wenn grün |
| Frontend `check`/`test`/`build` | ~30 min inkl. erstem Build im neuen Worktree |
| Restyling `CredentialStore`/`Account` | 60–90 min — die einzige Gestaltungsarbeit |
| Laufender Nachweis (4–5 Aussagen) | ~30 min |
| `FORK_CHANGES` neu + Detektorlauf + drei Doku-Updates | ~45 min |

Zusätzlich **~1 h Puffer**, falls die Backend-Suite einen Laufzeitfehler zutage fördert: die
Probe hat „mergt und kompiliert" bewiesen, „verhält sich richtig" hat bisher niemand geprüft.

> Verweise auf `docs/UPSTREAM_0.11.0_TRIAGE.md` und `docs/CUSTOM_CSS.md` beziehen sich auf
> Dateien, die es auf `main` gibt, im Quellbranch aber nicht — dort also erst nach dem Merge.
