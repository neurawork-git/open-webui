# LDAP-Credential-Store + SharePoint-Backend-Auswahl

> Fork-Feature. Macht LDAP-Anmeldedaten zu einem gleichrangigen Ersatz für OAuth überall
> dort, wo der Fork SharePoint anspricht. Gebaut für die KHKI-Instanz
> (Städtisches Krankenhaus Kiel), Farm `portal.skkiel.intern`, SharePoint Server SE.
>
> Lies das hier, bevor du `routers/knowledge.py` im SharePoint-Block, `ldap_auth` in
> `routers/auths.py` oder eines der `sharepoint_*`-Utils anfasst.

## 1. Warum es das gibt

Die Farm bietet ausschliesslich **NTLM** an — kein Negotiate, keine OIDC-Zone, kein Entra.
Ein delegierter Graph-Token ist damit nicht zu bekommen. Ein Dienstkonto ist vom Kunden
ausgeschlossen: jeder Nutzer soll genau das sehen, was er im SharePoint sehen darf. Bleibt
das Passwort des Nutzers, verschlüsselt verwahrt und eng begrenzt eingesetzt.

**Das Feature speichert AD-Passwörter.** Die Leitplanken in §5 sind Teil der Abnahme, nicht
Beiwerk.

OIDC 1.0 wäre der sauberere Weg — SharePoint SE kann das, und eine OIDC-Zone koexistiert
mit der NTLM-Zone. Bewusst verworfen (2026-07-31): der Aufwand liegt beim Kunden
(Entra-App, Nonce-Zertifikat je Farm-Server, neue Web-App-Zone, People-Picker) und die
Klinik-IT ist sehr ressourcenarm. Der LDAP-Weg ist damit nicht Übergang, sondern der
produktive Weg.

## 2. Architektur — eine Naht, zwei Implementierungen

Vorher entstand Credential-Material an genau einer Stelle
(`knowledge.py::_get_microsoft_access_token`) und ging als Bearer-String an `GraphClient`.
Diese Funktion ist ersetzt durch einen **Resolver**, der ein *Backend* liefert:

```
routers/knowledge.py  (9 Aufrufstellen)
    graph = await get_sharepoint_backend(request, user, db)
                    │
    SHAREPOINT_BACKEND ──┬── 'graph'  → GraphClient(bearer)          unverändert
                         └── 'onprem' → SharePointOnPremClient(NTLM)  neu
                                │
        beide erfüllen ─────────┴──→ SharePointBackend (Protocol, 9 Methoden)
```

`SharePointBackend` ist **wörtlich aus `GraphClient`s vorhandenen Signaturen** abgeleitet.
Deshalb erfüllt `GraphClient` es ohne eine Zeile Adaptercode — der Cloud-Pfad trägt kein
neues Risiko. Ein Test hält das fest
(`test_sharepoint_onprem_client.py::TestProtocolConformance`); bricht er, ist das Protocol
falsch abgeleitet, nicht `GraphClient`.

| Datei | Rolle |
|---|---|
| `utils/sharepoint_backend.py` | Protocol, Resolver, Schreibpfad, Löschregel. **Das Klartextpasswort verlässt dieses Modul nicht.** |
| `utils/sharepoint_onprem_client.py` | NTLM-Client (pyspnego + eigene `httpx.Auth`) |
| `models/user_credentials.py` | Verschlüsselter Speicher |
| `routers/users.py` | Drei Selbstverwaltungs-Endpunkte |

Tools bekommen über `__sharepoint__` in `extra_params` einen **fertigen Client**, nie ein
Credential. Ein Tool hat für einen Passwort-String keine Verwendung, die dieses Objekt
nicht schon erfüllt.

## 3. Was die Farm wirklich tut (gemessen 2026-07-31)

**Der v2.0-Dialekt kann auf dieser Farm keine Inhalte auflisten.** Eine frühere Messung
(2026-07-30, `khki-k8s/docs/SHAREPOINT_PERUSER_PRIMER.md`) notierte „9/11 Endpunkte 200"
und legte damit den Graph-kompatiblen Weg nahe. Gegen Bibliotheken **mit Inhalt** gemessen:

| Bibliothek | BaseTemplate | ItemCount | v2.0 `/children` | klassisch `/Files` |
|---|---:|---:|---:|---:|
| Abgabebibliothek | 101 | 0 | **200** | 0 |
| Dokumente | 101 | 0 | **200** | 0 |
| Dokumente der Websitesammlung | 101 | 0 | **200** | 0 |
| Dokumente zur Befragung | 101 | 3 | **400** | 3 |
| Bilder | 851 | 23 | **400** | 17 |
| Bilder der Websitesammlung | 851 | 11 | **400** | 4 |
| Seiten | 850 | 1 | **400** | 1 |
| Video News | 109 | 1 | **400** | 1 |

`/_api/v2.0/drives/{id}/root/children` antwortet **200 genau dann, wenn die Bibliothek leer
ist** — in jeder Adressierungsform. Die frühere Messung lief gegen leere Bibliotheken.

Deshalb: Ordner und Dateien über die klassische `_api/web`-Route. `/_api/v2.0/sites/...`
bleibt nur für die Site-Aufzählung, wo es belegt trägt.

| Zweck | Endpunkt |
|---|---|
| Identität | `/_api/web/currentUser` → `i:0#.w\|skkiel\<konto>` |
| Website | `<web>/_api/web?$select=Title,ServerRelativeUrl` |
| Unterwebsites | `<web>/_api/web/getsubwebsfilteredforcurrentuser(nWebTemplateFilter=-1,nConfigurationFilter=-1)` |
| Bibliotheken | `<web>/_api/web/lists?$expand=RootFolder`, gefiltert auf `BaseTemplate ∈ {101, 119}` und `Hidden == false` |
| Ordner + Dateien | `<web>/_api/web/GetFolderByServerRelativeUrl('<pfad>')?$expand=Folders,Files` |
| Download | `<web>/_api/web/GetFileByServerRelativeUrl('<pfad>')/$value` |
| Seitentext | `<web>/_api/web/lists(guid'…')/items?$select=…,WikiField` bzw. `…,CanvasContent1` |
| Termine | `<web>/_api/web/lists(guid'…')/items?$filter=EndDate ge datetime'…Z'` |

`<web>` ist kein Schmuck — siehe § 3.1.

Tot: `/_api/search/query` → 500 (kein Search Service, also **keine Volltextsuche**),
`/_api/web/folders` → 401, `/_api/v2.0/.../pages` → 404.
`/_api/v2.0/.../drives` meldet 8 von 27 Bibliotheken und für jede `quota.used = 0` — Menge
und Größen beide falsch, deshalb nicht benutzt.

### 3.1 Discovery: warum Websitesammlungen konfiguriert werden (gemessen 2026-08-04)

Die frühere Anbindung sah **2 von 122 Websites**. Sie begann bei `/_api/v2.0/sites/root`
plus `/sites/root/sites` — das liefert die Root-Websitesammlung und deren *direkte*
Unterwebsites. `/wissen`, `/abteilungen` und `/teamseiten` sind eigene **Websitesammlungen**
und können dort nicht auftauchen. 16.188 Listeneinträge (80 %) waren unsichtbar.

Es gibt keinen Aufruf, der Websitesammlungen aufzählt:

| Weg | Ergebnis |
|---|---|
| `/_api/v2.0/sites` | 400 `Cannot enumerate sites` |
| `/_api/v2.0/sites?search=*`, `/_api/search/query?…contentclass:STS_Site` | 500 (Suchdienst) |
| `/_vti_bin/SiteData.asmx`, `/_vti_bin/Webs.asmx` | 401 |
| `/_api/web/Navigation/MenuState` | 404 (Managed Navigation nicht in Betrieb) |

Deshalb werden sie **konfiguriert**: `sharepoint.onprem.site_roots` (§ 6). Für KHKI
`/,/wissen,/abteilungen,/teamseiten,/projekte` — abgelesen aus der Suite-Navigation des
Portals. `/projekte` gehört mit hinein, obwohl das Dienstkonto dort 401 bekommt: ein Konto
mit Rechten sieht die Sammlung dann ohne weitere Konfiguration.

**Innerhalb** einer Sammlung dagegen geht es: `/_api/web/webs` ist zwar 401 — das stand als
„Unterwebsites nicht enumerierbar" im Client-Kommentar und war ein Fehlschluss — aber
`getsubwebsfilteredforcurrentuser` antwortet 200 und ist permission-getrimmt, also sogar die
korrektere Quelle. 20 Aufrufe über eine bestehende Verbindung in 1,07 s; ein voller
Durchlauf über 122 Websites ~7 s.

> **Microsoft dokumentiert diese Methode als „Available in SharePoint Online only".**
> Auf dieser Farm ist sie gemessen 200. Die Messung schlägt die Doku — wer beim Aufräumen
> darüber stolpert, darf **nicht** auf `/_api/web/webs` zurückbauen. Das ist 401 und war
> genau die Ursache der ursprünglichen Blindheit.

Der Durchlauf ist pro AD-Konto gecacht (TTL 15 min) — die Sicht ist rechteabhängig, ein
gemeinsamer Cache wäre ein Rechteleck. Der Cache liegt modulweit, weil `_onprem_backend`
pro Request einen neuen Client samt NTLM-Handschlag baut. Grenzen: Tiefe 6, 500 Websites,
**beide protokolliert, wenn sie greifen** — eine stille Kürzung liest sich wie
Vollständigkeit.

### 3.2 Website-Kontext: 200 mit leerer Liste ist der gefährlichste Fall

Dieselbe Bibliothek, drei Aufrufkontexte (`/wissen/HygieneInfo/Hygiene Handbuch`, 194 Dateien):

| Aufruf | `/` (Root) | `/wissen` (Sammlung) | `/wissen/HygieneInfo` (Website) |
|---|---|---|---|
| `GetFolderByServerRelativeUrl?$expand=Folders,Files` | 401 | **200, 0 Dateien** | 200, **194 Dateien** |

Der mittlere Fall ist der gefährliche: HTTP 200, korrekter Ordnername, leere Dateiliste.
Wer nur den Statuscode prüft, hält den Ordner für leer. Das gilt **auch innerhalb** einer
Sammlung: `/blog/SiteAssets` liefert aus dem Root-Kontext 0 statt 334 Dateien — der Defekt
war also schon vor der Discovery-Erweiterung wirksam.

Deshalb stellt jeder Datei-Aufruf den Website-Pfad voran, ermittelt als **längster bekannter
Web-Pfad, der Präfix der Ziel-URL ist** (`_web_for`, Segmentgrenzen, case-insensitiv). Ist
nichts bekannt, wird die Discovery angestossen statt Root geraten. Und ein Listing mit 0
Dateien *und* 0 Ordnern, dessen Liste `ItemCount > 0` meldet, wird als Kontextverdacht
gemeldet statt als leerer Ordner.

Nebenbei behoben: `_site_prefix` gab für die v2.0-GUID-IDs `''` zurück, weshalb der Picker
für **jede** Website die Bibliotheken der Root-Website zeigte. Website-IDs sind jetzt
server-relative Pfade. Die Datei-IDs (`spo_<base64>`) sind **unverändert**, damit bestehende
Wissensdatenbank-Importe auflösbar bleiben.

### 3.3 Inhalte jenseits von Dokumentbibliotheken

7.290 der 20.180 Einträge (36 %) liegen nicht in Dokumentbibliotheken.

- Bibliotheks-Filter ist `{101, 119}`. 119 (Websiteseiten) trägt den Portalinhalt und wird
  im Picker als `drive_type: 'pages'` ausgewiesen. Ein **Website-Volimport überspringt sie**:
  `.aspx` sind Markup-Hüllen, ihr Text steht in Listenfeldern.
- `read_page(site_path, page)` liest `WikiField` (klassisch) bzw. `CanvasContent1` (modern).
  **Zwei getrennte Abfragen, nicht ein `$select` mit beiden Feldern** — auf einer klassischen
  SP2016-Website existiert `CanvasContent1` womöglich nicht, und ein unbekanntes Feld im
  `$select` lässt die *ganze* Abfrage mit 400 scheitern. Erkennung über Statuscode, nicht
  über den (lokalisierten) Meldungstext. Die Bibliothek wird über `BaseTemplate eq 119`
  gefunden, nicht über `getbytitle('Site Pages')` — die Farm ist deutsch („Websiteseiten").
- `list_events(site_path, from_date, top)` liest Kalender (106). Das Datumsliteral **muss**
  `datetime'…Z'` sein (OData v2/v3); ein blosser ISO-String ist ungültig. Serientermine
  kommen nur als Serienkopf zurück — `DateTimeRangesOverlap` ist in `$filter` ausdrücklich
  nicht unterstützt — und werden als `recurring` markiert statt stillschweigend für alle
  Termine zu stehen.
- `read_page`, `list_events`, `resolve_url` und `list_webs` sind **nicht** im
  `SharePointBackend`-Protokoll. Jede Methode dort wäre eine Pflicht für `GraphClient`.
  Aufrufer greifen direkt auf den On-Prem-Client zu und prüfen mit `hasattr`.

## 4. Fallstricke, die Geld kosten

1. **401 heisst hier nicht immer „Passwort falsch".** Die Farm antwortet 401 auch für einen
   Pfad, den es nicht gibt. Der Client prüft deshalb bei jedem 401 einmal
   `/_api/web/currentUser` auf derselben, bereits authentifizierten Verbindung nach: löst
   die Identität weiterhin auf → **404**. Nur ein 401, das diese Probe überlebt, gilt als
   Ablehnung und löscht das Credential. Es wird dabei kein Passwort erneut gesendet.
2. **Kein Retry nach echtem 401.** Ein fehlgeschlagener NTLM-Durchgang zählt auf denselben
   `badPwdCount` wie ein LDAP-Bind. Domänenrichtlinie: **5 Fehlversuche, 15 Minuten
   Sperre**; bei nicht erreichbarem PDC-Emulator zählt ein Versuch mitunter mehrfach. Eine
   Wiederholschleife sperrt ein Konto in Sekunden.
3. **`Accept: application/json` ohne `odata=`.** Mit `odata=nometadata` antworten die
   v2.0-Endpunkte 400 `invalidRequest`.
4. **NTLM authentifiziert die TCP-Verbindung, nicht den Request.** Deshalb ein dedizierter
   `AsyncClient` je Credential mit `max_connections=1` und `http2=False`. httpx garantiert
   von sich aus nicht, dass die drei Handshake-Legs dieselbe Verbindung nehmen.
5. **Apostrophe in Dateinamen** beenden das OData-Stringliteral vorzeitig → 400.
   Verdoppeln, dann URL-kodieren.
6. **Systemordner** (`Forms`, `_t`, `_w`, `_catalogs`) werden gefiltert — sonst landen
   Formularvorlagen und Thumbnail-Caches in der Wissensdatenbank.
7. **IDs dürfen keine Slashes enthalten.** `drive_id` und `item_id` reisen als
   FastAPI-**Pfadparameter**, und die matchen kein `/`. Serverrelative URLs direkt
   herauszugeben machte `/sharepoint/drives/{drive_id}/items/{item_id}/children`
   unerreichbar — gefunden erst im End-to-End-Lauf, nicht von den Unit-Tests. Deshalb
   opake `spo_<base64url>`-Tokens (`encode_id`/`decode_id`). Prozentkodierung ist kein
   Ausweg: viele Reverse-Proxies normalisieren oder verwerfen `%2F`.
   Darunter sind es weiterhin Pfade, also **brechen sie beim Umbenennen und Verschieben**;
   ein Re-Import meldet die Datei dann als fehlend. Ausweg wäre `(Listen-GUID, Item-ID)`.
8. **Keine Paginierung.** Die klassischen Collections liefern alles in einer Antwort;
   `next_link` ist immer `None`. Grenze ist der List View Threshold (5000). Grösste
   KHKI-Bibliothek: 350 Elemente.

## 5. Leitplanken (Teil der Abnahme)

1. **Speichern ist der Default, kein Dialog.** Solange das Feature-Flag an ist, legt
   jeder LDAP-Login das Kennwort ab. Unterdrückt wird das nur durch ein **explizites
   Opt-out**, das der Nutzer selbst setzt — und das persistiert wird. Ohne diese
   Persistenz würde der nächste Login eine Löschung sofort rückgängig machen und der
   Lösch-Endpunkt wäre Theater. Kann der Store den Zustand nicht lesen, wird **nicht**
   gespeichert (fail closed).
2. **Harte TTL** (`LDAP_CREDENTIAL_TTL`, Vorschlag 30 Tage). Die Domäne hat
   `maxPwdAge = nie`, Passwörter laufen also nicht von selbst aus; die TTL ist die
   einzige Begrenzung der Verwahrdauer.
3. **Eigener Schlüssel.** `LDAP_CREDENTIAL_ENCRYPTION_KEY` fällt **nicht** auf
   `WEBUI_SECRET_KEY` zurück — sonst hängen Sitzungssignatur und Passwortverwahrung am
   selben Wert und eine Rotation zerstört beides. Fehlt er, startet der Store nicht.
4. **AES-256-GCM statt Fernet**, mit `user_id` als AAD. Ohne die AAD-Bindung könnte
   jemand mit DB-Schreibzugriff das Chiffrat von Nutzer A in die Zeile von Nutzer B
   kopieren und unter fremder Identität auf SharePoint zugreifen — bei einem
   Rechtetrennungs-Feature genau der Angriff, der zählt.
5. **Kein Endpunkt gibt das Geheimnis heraus**, auch kein Admin-Endpunkt. Der Verzicht ist
   absichtlich: `GET /api/v1/auths/admin/config/ldap/server` liefert das Bind-Passwort im
   Klartext zurück — dieser Fehler wird hier nicht wiederholt.
6. **Feature-Flag** `ENABLE_LDAP_CREDENTIAL_STORE`, Standard `false`.

Zur Auditfähigkeit: NIST SP 800-63B stuft reversible Passwortspeicherung als nicht konform
ein. Das zielt auf *Verifier*-Systeme; wir sind keiner, weil wir das Klartextpasswort für
die Weitergabe an SPSE brauchen. Ein Prüfer wird es trotzdem anmerken. Kompensierend:
Schlüssel ausserhalb der DB, Audit bei jeder Entschlüsselung, kurze TTL, dokumentierte
Risikoakzeptanz der Fachseite.

## 6. Konfiguration

```yaml
# khki-k8s/values/production/open-webui.yaml
openwebui:
  env:
    ENABLE_LDAP_CREDENTIAL_STORE: "true"
    LDAP_CREDENTIAL_TTL: "2592000"        # 30 Tage
    LDAP_NETBIOS_DOMAIN: "skkiel"
    SHAREPOINT_BACKEND: "onprem"
    SHAREPOINT_ONPREM_SITE_URL: "https://portal.skkiel.intern"
    SHAREPOINT_ONPREM_VERIFY_TLS: "false"  # bis die interne CA im Pod-Truststore liegt
    SHAREPOINT_ONPREM_SITE_ROOTS: "/,/wissen,/abteilungen,/teamseiten,/projekte"
    # LDAP_CREDENTIAL_ENCRYPTION_KEY kommt aus einem Secret, nicht aus den Values.
    # Erzeugen: python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

`SHAREPOINT_ONPREM_SITE_ROOTS` ist nur der **Startwert**. Gepflegt wird die Liste danach
unter **Admin → Authentifizierung → SharePoint → Websitesammlungen**
(`sharepoint.onprem.site_roots`, `GET`/`POST /api/v1/auths/admin/config/sharepoint`). Kommt
eine Websitesammlung dazu, ist das damit eine Betriebsänderung von Minuten statt eines
Deployments mit Pod-Neustart — und die Änderung greift beim nächsten Aufruf, ohne auf den
Discovery-Cache zu warten (der Cache-Schlüssel enthält die Einstiegspunkte).

Der Abschnitt erscheint im Admin-Panel **nur bei `SHAREPOINT_BACKEND=onprem`**: die
Endpunkte antworten sonst 404, und dieses 404 ist das Gate. Ein zusätzliches Feature-Flag
gibt es dafür bewusst nicht.

Default ohne jede Konfiguration ist `/` — eine ungepflegte Instanz verhält sich damit exakt
wie vor der Discovery-Erweiterung.

Schlüsselrotation: Es gibt einen aktiven Schlüssel. Eine Rotation entwertet alle
Datensätze; jeder Nutzer legt sein Credential beim nächsten Login neu an. Das wird
**lokal** über die Spalte `key_id` erkannt, es erreicht also kein Fehlversuch den
Domänencontroller.

## 7. Tests

| Datei | Deckt ab |
|---|---|
| `test/test_user_credentials.py` | Krypto (Roundtrip, AAD, Nonce, Tampering), Schlüsselvalidierung, TTL, Upsert, Opt-in, Rotation, **und dass kein Geheimnis in Antwort oder Log landet — inklusive Fehlerpfade** |
| `test/sharepoint/test_sharepoint_onprem_client.py` | NTLM-Legs, Endpunkt-Mapping, Systemordner-Filter, Apostroph-Escaping, 401-Unterscheidung, Protokoll-Konformität beider Clients |
| `test/sharepoint/test_sharepoint_import_onprem.py` | Die **KB-Import-Endpunkte** über das On-Prem-Backend: Ordner-Import, Einzeldatei, Listing, `backend`-Feld in `sharepoint_source`, 409 beim Re-Import gegen das falsche Backend, und dass ein echter 401 das Credential genau einmal verwirft |
| `test/sharepoint/test_sharepoint_import.py` | Bestehende Import-Tests (Graph-Pfad), auf den Resolver umgezogen |
| `test/sharepoint/test_sharepoint_onprem_discovery.py` | Normalisierung der Einstiegspunkte, rekursive Discovery über mehrere Sammlungen, übersprungene 401-Zweige, beide OData-Verbositäten, Tiefen-/Anzahlgrenze samt Log, Cache (Treffer, fremdes Konto, geänderte Einstiegspunkte, Ablauf), Kontextauflösung inkl. `/wissen` vs. `/wissenschaft`, Kontextverdacht, navigierbare Liste, `_site_prefix` |
| `test/sharepoint/test_sharepoint_onprem_pages_events.py` | `read_page` (Wiki, modern, fehlendes `CanvasContent1`, WebPart-Hinweis, Template-statt-Titel), `list_events` (Datumsliteral, Serienkopf, `$top`, unlesbarer Kalender), `resolve_url`, und dass Seitenbibliotheken sichtbar aber nicht importierbar sind |

`conftest.py` leert den modulweiten Discovery-Cache um jeden Test. Ohne das liest ein
späterer Test die Farm des früheren, sein eigener Mock-Transport wird nie befragt — und er
wird grün aus dem falschen Grund.

## 8. Rückwärtskompatibilität

Das Feature existiert für **einen** Kunden. Alle anderen Instanzen (Falkensteg, Stadtbau,
intern) müssen sich exakt wie vorher verhalten. Festgenagelt in
`test/sharepoint/test_sharepoint_backend_compat.py`, nicht bloss behauptet.

**Defaults ohne jede Konfiguration:** `SHAREPOINT_BACKEND=graph`,
`ENABLE_LDAP_CREDENTIAL_STORE=false`, kein Schlüssel. Die Instanz bootet, `is_onprem()` ist
`False`, der Graph-Pfad läuft.

**Der Graph-Credential-Pfad ist wörtlich derselbe.** `_graph_backend` in
`utils/sharepoint_backend.py` ist die verschobene Fassung des früheren
`knowledge.py::_get_microsoft_access_token`; der einzige funktionale Unterschied ist
`return GraphClient(access_token)` statt `return access_token`. Die drei Graph-Fehlertexte
sind wortgleich — Runbooks zitieren sie.

**Was sich trotzdem ändert, unabhängig vom Flag** — alles additiv, keine Verhaltensänderung:

| Änderung | Wirkung auf Graph-Instanzen |
|---|---|
| Migration legt `user_credential` an | leere Tabelle, sonst nichts |
| `sharepoint_source` bekommt `backend: 'graph'` | zusätzliches Feld bei neuen Importen |
| `extra_params` bekommt `__sharepoint__` | immer `None`, ohne DB-Zugriff |
| `SharePointDriveSummary.item_count` | zusätzliches Feld, Wert `0` |
| `_translate_graph_error` ist async | rein intern, gleiche Texte |
| `maybe_store_ldap_credential` im LDAP-Login | kehrt sofort zurück, wirft nie |

**Bestehende Wissensdatenbanken:** Vor dieser Änderung importierte Quellen haben kein
`backend`-Feld. Ein fehlender Wert gilt als `graph` — solche KBs sind älter als der
On-Prem-Pfad, können also nur von Graph stammen. Sie laufen unverändert weiter. Nur eine
Quelle vom **anderen** Backend wird mit 409 abgelehnt; das ist besser, als fremde IDs
gegen die falsche Farm aufzulösen.

**Wenn der Store kaputt ist** (fehlender Schlüssel, DB-Fehler), scheitert **kein** Login:
der Schreibpfad fängt, loggt ohne Wert und macht weiter. Ein Credential-Speicher darf
niemanden aussperren.

## 9. Live-Verifikation

Gegen `portal.skkiel.intern` am 2026-07-31 mit einem echten AD-Konto durchlaufen:
Identität `i:0#.w|skkiel\<konto>` (claims-basiert, **kein Dienstkonto**), 7 Bibliotheken,
Ordnerlisting, rekursiver Walk, Download byte-genau (226.966 B, `%PDF-1.7`),
Metadaten-Roundtrip.

Zusätzlich end-to-end über die **echten HTTP-Routen** (ASGI, Session-Nutzer gemockt):
`/users/user/credentials/status`, `/knowledge/sharepoint/sites`,
`/sharepoint/sites/{id}/drives`, `/sharepoint/drives/{id}/items/{iid}/children` — letzterer
liefert die drei echten PDFs. Ebenso geprüft: Opt-out hält über den nächsten Login hinweg,
und ohne Credential kommt ein sprechender 401.

**Der KB-Import selbst ist live durchgelaufen** (2026-08-03): Wissensdatenbank anlegen →
`list-folder` → `import-file` → Datei liegt als File-Objekt vor, ist über
`knowledge_file` mit der KB verknüpft, und aus dem PDF wurden 3.162 Zeichen extrahiert.
`persist-source` schreibt `backend: onprem`.

Zwei Stolpersteine, falls jemand diesen Lauf nachstellt:
- `httpx.ASGITransport` fährt den **Lifespan nicht hoch**, und dort wird `app.state.ef`
  gesetzt — ohne `app.router.lifespan_context(app)` scheitert der Import mit
  `'State' object has no attribute 'ef'`.
- Die KB-Mitgliedschaft steht in der Tabelle `knowledge_file`, **nicht** im `files`-Feld
  der KB-Antwort. `Knowledges.has_file(kb_id, file_id)` ist die verlässliche Prüfung.
  `add_file_to_knowledge_by_id` verschluckt zudem jede Exception und liefert `None` —
  ein stiller Fehlschlag sieht dort aus wie ein Erfolg.

**Noch offen:** die Gegenprobe mit einem zweiten, geringer berechtigten Konto. Erst sie
weist die Rechtetrennung nach — ein erfolgreicher Durchlauf mit einem Konto zeigt nur, dass
Zugriff funktioniert, nicht dass er korrekt begrenzt ist.
