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
| Sites | `/_api/v2.0/sites/root` + `/sites/root/sites` |
| Bibliotheken | `/_api/web/lists?$expand=RootFolder`, gefiltert auf `BaseTemplate == 101` und `Hidden == false` |
| Ordner + Dateien | `/_api/web/GetFolderByServerRelativeUrl('<pfad>')?$expand=Folders,Files` |
| Download | `/_api/web/GetFileByServerRelativeUrl('<pfad>')/$value` |

Tot: `/_api/search/query` → 500 (kein Search Service, also **keine Volltextsuche**),
`/_api/web/webs` und `/_api/web/folders` → 401, `/_api/v2.0/.../pages` → 404.
`/_api/v2.0/.../drives` meldet 8 von 27 Bibliotheken und für jede `quota.used = 0` — Menge
und Größen beide falsch, deshalb nicht benutzt.

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
    # LDAP_CREDENTIAL_ENCRYPTION_KEY kommt aus einem Secret, nicht aus den Values.
    # Erzeugen: python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

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

## 8. Live-Verifikation

Gegen `portal.skkiel.intern` am 2026-07-31 mit einem echten AD-Konto durchlaufen:
Identität `i:0#.w|skkiel\<konto>` (claims-basiert, **kein Dienstkonto**), 7 Bibliotheken,
Ordnerlisting, rekursiver Walk, Download byte-genau (226.966 B, `%PDF-1.7`),
Metadaten-Roundtrip.

Zusätzlich end-to-end über die **echten HTTP-Routen** (ASGI, Session-Nutzer gemockt):
`/users/user/credentials/status`, `/knowledge/sharepoint/sites`,
`/sharepoint/sites/{id}/drives`, `/sharepoint/drives/{id}/items/{iid}/children` — letzterer
liefert die drei echten PDFs. Ebenso geprüft: Opt-out hält über den nächsten Login hinweg,
und ohne Credential kommt ein sprechender 401.

**Noch offen:** die Gegenprobe mit einem zweiten, geringer berechtigten Konto. Erst sie
weist die Rechtetrennung nach — ein erfolgreicher Durchlauf mit einem Konto zeigt nur, dass
Zugriff funktioniert, nicht dass er korrekt begrenzt ist.
