# Plan: LDAP-Credential-Store für den Pilotbetrieb (KHKI)

> **Überholt von** [`.claude/PRPs/plans/ldap-sharepoint-credential-backend.plan.md`](../.claude/PRPs/plans/ldap-sharepoint-credential-backend.plan.md)
> (2026-07-31). Dieses Dokument beschreibt den Credential-Store für ein einzelnes Tool; der
> Nachfolger macht daraus einen austauschbaren Credential- **und** Backend-Pfad für alle
> SharePoint-Endpunkte. Korrigiert dort: Opt-in-Speicherort, `entry_username` als Listenwert,
> Schlüssel-Fallback, und der Verzicht darauf, Tools ein Klartext-Passwort zu reichen.
> Die Abschnitte 8 (Leitplanken) und 13 (Ausstieg) hier gelten unverändert weiter.

Stand 2026-07-31. Grundlage für ein Fork-Feature, das das AD-Passwort eines per LDAP
angemeldeten Nutzers verschlüsselt ablegt, damit Tools im Namen dieses Nutzers gegen
NTLM-geschützte On-Prem-Dienste sprechen können — konkret SharePoint SE der
Städtischen Krankenhaus Kiel.

**Dieses Feature speichert AD-Passwörter. Es ist eine bewusst befristete Brücke, kein
Zielbild.** Die Abschnitte „Leitplanken" und „Ausstieg" sind nicht schmückendes Beiwerk,
sondern Teil der Abnahme.

## 1. Warum überhaupt

Gemessen am 2026-07-30/31 gegen `portal.skkiel.intern` (Details:
`khki-k8s/docs/SHAREPOINT_PERUSER_PRIMER.md`):

- Die Farm bietet ausschliesslich **NTLM** an, kein Negotiate, keine OIDC-Zone. Ein
  Zugriff braucht also Kontoname **und** Passwort des Nutzers.
- Der LDAP-Login liefert kein wiederverwendbares Artefakt: `ldap_auth` in
  `backend/open_webui/routers/auths.py` macht einen Simple Bind mit dem Dienstkonto
  (Suche) und einen zweiten mit den Nutzerdaten (Prüfung). Ergebnis ist ein Boolean.
  Das Passwort lebt nur im Request; beim Anlegen des Kontos schreibt OWUI sogar ein
  Zufallspasswort in die eigene Datenbank (`password=str(uuid.uuid4())`).
- Aus dem Login lässt sich damit nur der **Kontoname** dauerhaft gewinnen (`cn` landet
  in `user.name`, bei gesetztem `attribute_for_username` in `user.username`).

Ein Dienstkonto ist vom Kunden ausgeschlossen — jeder Nutzer soll genau das sehen, was
er im SharePoint sehen darf. Bleibt für die Pilotphase: das Passwort des Nutzers, sicher
verwahrt und eng begrenzt eingesetzt.

## 2. Ziel und Nicht-Ziele

**Ziel:** Ein per LDAP angemeldeter Nutzer kann SharePoint-Tools benutzen, ohne sein
Passwort ein zweites Mal irgendwo einzutragen, und ohne dass es im Klartext in der
Datenbank steht.

**Nicht-Ziele:**

- Kein Ersatz für Kerberos S4U oder eine OIDC-Zone — beide bleiben das Zielbild.
- Keine Nutzung durch Hintergrundjobs ohne aktive Sitzung (siehe Variante B).
- Kein Speichern von Passwörtern für Konten, die sich nicht per LDAP anmelden.
- Keine Ausgabe des Geheimnisses über irgendeine REST-Schnittstelle. Nie.

## 3. Zwei Varianten — bewusst entscheiden

| | **A: Server-Schlüssel** | **B: Sitzungsgebunden** |
|---|---|---|
| Schlüssel | eigener Key aus K8s-Secret | aus dem Nutzerpasswort abgeleitet (Argon2id/PBKDF2), Klarschlüssel nur im Sitzungscache |
| Ruhezustand | Anwendung kann jederzeit entschlüsseln | ohne aktive Sitzung nicht entschlüsselbar |
| Schützt gegen | DB-Diebstahl, Backups | zusätzlich: Cluster-Admin, Pod-Zugriff, Insider |
| Nutzung ohne Sitzung | ja | nein |
| Aufwand | ~1 Tag | ~2–3 Tage (Sitzungscache, Ableitung, Invalidierung) |

**Empfehlung: mit A beginnen, B als Ausbaustufe vorsehen** — der Datenzugriff im Tool
erfolgt in beiden Fällen über dieselbe Funktion, nur die Schlüsselherkunft ändert sich.
Wer A wählt, muss ehrlich kommunizieren: das schützt Backups, nicht vor Cluster-Admins.

## 4. Datenmodell

Blaupause ist `backend/open_webui/models/oauth_sessions.py` — dort ist das Muster
„verschlüsselte Geheimnisse pro Nutzer" bereits umgesetzt (Fernet, eigener Env-Key,
eigene Tabelle mit Indizes, Pydantic-Modell daneben).

Neue Datei `backend/open_webui/models/user_credentials.py`:

```python
class UserCredential(Base):
    __tablename__ = 'user_credential'

    id = Column(Text, primary_key=True)          # uuid4
    user_id = Column(Text, nullable=False)
    realm = Column(Text, nullable=False)         # 'ad' — Raum für weitere Systeme
    account = Column(Text, nullable=False)       # DOMAIN\benutzer, im Klartext (kein Geheimnis)
    secret = Column(Text, nullable=False)        # Fernet-Chiffrat des Passworts
    expires_at = Column(BigInteger, nullable=False)   # harte TTL, siehe Leitplanken
    last_used_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('idx_user_credential_user_realm', 'user_id', 'realm', unique=True),
        Index('idx_user_credential_expires_at', 'expires_at'),
    )
```

Migration als Alembic-Revision unter `backend/open_webui/migrations/versions/`,
Namensschema wie die vorhandenen Dateien. Downgrade muss die Tabelle löschen — beim
Zurückrollen darf kein Geheimnis liegen bleiben.

## 5. Schreibpfad

In `routers/auths.py`, Funktion `ldap_auth`, unmittelbar nach dem erfolgreichen
Nutzer-Bind (dort, wo heute `raise HTTPException(400, 'Authentication failed.')` steht,
im Erfolgszweig darunter):

```python
if LDAP_CREDENTIAL_STORE_ENABLED and await UserCredentials.is_opted_in(user.id):
    await UserCredentials.upsert(
        user_id=user.id,
        realm='ad',
        account=f'{LDAP_NETBIOS_DOMAIN}\\{entry_username}',
        secret=form_data.password,          # verschlüsselt in der Methode, nicht hier
        ttl_seconds=LDAP_CREDENTIAL_TTL,
    )
```

Wichtig:

- **Opt-in ist Voraussetzung**, nicht Standard. Ohne Einwilligung wird nichts abgelegt
  (Abschnitt 8).
- Das Passwort wird ausschliesslich in der Modellschicht verschlüsselt; der Router sieht
  nie ein Chiffrat und legt nie selbst etwas ab.
- Bei jedem erfolgreichen Login wird der Eintrag überschrieben — damit ist ein
  Passwortwechsel automatisch nach der nächsten Anmeldung wieder korrekt.
- `entry_username` statt `form_data.user`: der Wert kommt aus dem Verzeichnis, nicht aus
  der Eingabe.

## 6. Lesepfad (für Tools)

Neue Datei `backend/open_webui/utils/user_credentials.py` mit genau einer öffentlichen
Funktion, damit Tools nichts eigenes bauen:

```python
async def get_ad_credential(user_id: str) -> tuple[str, str] | None:
    """(account, password) oder None. Aktualisiert last_used_at. Nur prozessintern."""
```

Ein Tool benutzt sie per Direct Import (Muster wie in `open-webui-toolkit/tools/*`):

```python
from open_webui.utils.user_credentials import get_ad_credential
cred = await get_ad_credential(__user__["id"])
```

Regeln:

- **Kein REST-Endpunkt gibt das Geheimnis heraus.** Der Verzicht ist absichtlich: die
  Admin-API der LDAP-Konfiguration (`/api/v1/auths/admin/config/ldap/server`) liefert das
  Bind-Passwort im Klartext zurück — genau dieser Fehler wird hier nicht wiederholt.
- Rückgabewerte nie loggen, nie in Fehlermeldungen aufnehmen, nie in Tool-Antworten
  spiegeln.
- Bei abgelaufener TTL liefert die Funktion `None` und löscht den Eintrag.

## 7. API-Oberfläche (bewusst minimal)

| Endpunkt | Zweck |
|---|---|
| `GET /api/v1/users/user/credentials/status` | nur Metadaten: vorhanden ja/nein, Konto, `expires_at`, `last_used_at` |
| `POST /api/v1/users/user/credentials/opt-in` | Einwilligung setzen/entziehen |
| `DELETE /api/v1/users/user/credentials/ad` | eigenes Geheimnis sofort löschen |

Alle drei ausschliesslich für das **eigene** Konto. Admins bekommen **keinen** Lesezugriff
auf fremde Einträge; ein Admin darf höchstens löschen (dann per Audit-Eintrag).

## 8. Leitplanken — Teil der Abnahme

1. **Opt-in mit klarem Text.** Der Nutzer sieht vor der Speicherung, was passiert: sein
   AD-Passwort wird verschlüsselt hinterlegt, um in seinem Namen auf SharePoint
   zuzugreifen; er kann es jederzeit löschen; der Pilot endet am `<Datum>`.
2. **Harte TTL** (`LDAP_CREDENTIAL_TTL`, Vorschlag 30 Tage). Danach ist der Eintrag
   wertlos und wird gelöscht — der nächste Login legt ihn neu an. Die TTL begrenzt hier
   nicht den Passwortablauf, sondern die Verwahrdauer: die Domäne hat **`maxPwdAge = nie`**
   (gemessen 2026-07-31), Passwörter laufen also nicht von selbst aus. Damit gilt: ein
   gespeichertes Geheimnis bleibt gültig, bis der Mensch es ändert — gut für die
   Zuverlässigkeit, schlecht für den Schadensfall. Die TTL ist die einzige Begrenzung.
3. **Kein Retry nach 401.** Schlägt eine Anmeldung mit gespeichertem Geheimnis fehl,
   wird der Eintrag **gelöscht** und der Nutzer zur Neuanmeldung aufgefordert. Gemessene
   Domänenrichtlinie: **5 Fehlversuche**, Sperrdauer **15 Minuten**, Zählfenster
   **15 Minuten**, keine Fine-Grained Policies. Eine Sperre heilt also von selbst, aber
   ein Tool in einer Wiederholschleife sperrt ein Konto binnen Sekunden.
4. **Audit-Einträge** für Anlegen, Verwenden, Löschen, Ablauf — ohne den Geheimniswert.
5. **Eigener Schlüssel** `LDAP_CREDENTIAL_ENCRYPTION_KEY` aus einem K8s-Secret, nicht
   `WEBUI_SECRET_KEY` mitbenutzen: sonst hängen Sitzungssignatur und Geheimnisverwahrung
   am selben Wert, und eine Schlüsselrotation zerstört beides gleichzeitig.
6. **Feature-Flag** `ENABLE_LDAP_CREDENTIAL_STORE`, Standard `false`. Nur die
   KHKI-Instanz schaltet es ein.
7. **Nur begrenzter Nutzerkreis.** Umsetzung über eine Gruppe; wer nicht darin ist, für
   den greift der Schreibpfad nicht.

## 9. Konfiguration

```yaml
# khki-k8s/values/production/open-webui.yaml
openwebui:
  env:
    ENABLE_LDAP_CREDENTIAL_STORE: "true"
    LDAP_CREDENTIAL_TTL: "2592000"          # 30 Tage
    LDAP_NETBIOS_DOMAIN: "skkiel"
    # LDAP_CREDENTIAL_ENCRYPTION_KEY kommt aus einem Secret, nicht aus den Values
```

Ergänzend bleibt `ENABLE_VALVE_ENCRYPTION: "true"` sinnvoll (bereits vorbereitet) —
sobald der Credential-Store steht, entfallen die AD-Passwörter in den UserValves des
Tools `sharepoint_khki` und sollten dort gelöscht werden.

## 10. Tests

- **Modellschicht:** Verschlüsseln/Entschlüsseln, TTL-Ablauf liefert `None` und löscht,
  Upsert überschreibt statt zu duplizieren, Downgrade der Migration entfernt die Tabelle.
- **Router:** Login ohne Opt-in legt nichts an; Login mit Opt-in legt an; falsches
  Passwort legt nichts an.
- **Negativtest, der scharf sein muss:** kein Endpunkt und kein Log gibt das Geheimnis
  aus. Als Test formuliert: Antwortkörper und Logzeilen eines vollständigen Login- und
  Tool-Durchlaufs dürfen die Passwortzeichenkette nicht enthalten.
- **Integrationstest** gegen die KHKI-Instanz: Login → Tool-Aufruf → `/_api/web/currentUser`
  liefert `i:0#.w|skkiel\<konto>`, also die Identität des Nutzers, nicht die eines Dienstkontos.

## 11. Fork-Pflege

- Branch von **`feature/owui-0.10.2`** (Produktivstand KHKI, Image `git-f805abe`), danach
  Cherry-Pick nach `feature/owui-0.11.0`.
- Eintrag in `docs/FORK_CHANGES.md`: der Patch sitzt im Auth-Pfad, den Upstream häufig
  anfasst — beim Versionssprung gezielt prüfen, ob `ldap_auth` umgebaut wurde.
- Den Eingriff in `ldap_auth` so klein wie möglich halten (ein Aufruf), damit ein Rebase
  nicht in einer Konfliktwolke endet. Die Logik gehört in Modell- und Utils-Schicht.

## 12. Definition of Done

- [ ] Migration läuft vorwärts und rückwärts sauber gegen Postgres
- [ ] Feature-Flag aus, Standardverhalten unverändert (Regressionstest LDAP-Login)
- [ ] Opt-in-Dialog vorhanden, Text mit dem Kunden abgestimmt
- [ ] `sharepoint_khki` nutzt den Store statt der UserValves; Valve-Felder entfernt
- [ ] 401 löscht den Eintrag, kein zweiter Versuch (nachgewiesen im Test)
- [ ] Negativtest „kein Geheimnis in Antwort und Log" grün
- [ ] Audit-Einträge sichtbar
- [ ] Pilot-Enddatum schriftlich fixiert, Löschlauf für das Ende vorbereitet

## 13. Ausstieg

Der Store wird abgeschaltet, sobald einer der beiden Zielwege steht:

- **Kerberos S4U** (Negotiate auf der Zone + eingeschränkte Delegation für ein
  Dienstkonto): Identität bleibt Windows-Claim, Berechtigungen greifen unverändert.
- **OIDC-Zone** (Entra-Tenant `62ac6d77-ef7d-469d-adbe-8a278e496cf3` existiert, Domain
  ist „Managed"): Tokens statt Passwörter, OWUI liefert mit `auth_type: oauth_2.1`
  bereits einen verschlüsselten Token-Store pro Nutzer.

Beim Abschalten: Flag auf `false`, Tabelle per Migration leeren und löschen, Nutzer
informieren. Die Entscheidung darüber gehört dem Kunden — dieser Plan liefert die
Brücke, nicht das Fundament.
