# Notification-Inbox Phase A1: vorab präzisierter Quellenvertrag

03.10.2026; eigener Checkout `work/dashboard-notification-timestamps`.
Freigabe: Root hat die erste Phase des Plans `2d1002c` autorisiert.
Dieses Dokument präzisiert vor den Produktänderungen deren konkrete Interfaces.

## Quellen und Grenzen

- `backend/services/notification_inbox_types.py`: reine Pydantic-DTOverträge
  für Livequery/Page/Item/Readresult sowie intern eingefrorener `InboxPrincipal`.
  Keine Actorfelder in Request-DTOs; keine Auth/Config/Storeimports.
- `backend/db/notification_inbox_models.py`: ausschließlich
  `notification_read_states`, Paar-PK, User-/Notification-FKs mit CASCADE,
  verpflichtende erste UTC-Readzeit. Keine Selection-/Jobtabellen.
- `backend/services/notification_inbox_validation.py`: reiner read-only
  Raw-SQLite-/SQLAlchemy-Connectionvalidator. Separater struktureller
  `validate_notification_inbox_schema` und vollständiger streamender
  `validate_notification_inbox_database`, jeweils `deadline=None`.
  Ganze Schemaabwesenheit ist legacykompatibel; beschädigte Spalten/Keys/FKs/
  Zeitformen/Parentbezüge werden abgewiesen. Kein DDL/DML/ORM/Storeimport.
- `backend/services/notification_inbox.py`: ausschließlich SQL-Service,
  tatsächlicher SQLUserStore, native Datenbank-/Schemaidentität, gemeinsame
  Eligibility vor Counts/LIMIT, vorhandener HMAC-Cursor/Snapshotreader und
  verlustfreier SQLite-/PG-Zeitstempelsort. Kein Root-Chronologyimport.

Kein Router/HTTPwrite, keine globale Modellregistrierung, keine Migration,
kein Auth/Middleware/Job/Recovery/Referencecatalogedit. `l2` bleibt TEHA.
Expliziter Featuremodulimport definiert das eigene Modell; es wird nicht in
den Startup-/Migrationsimportlisten aktiviert. Root registriert später.

## Read-Schnittstelle

```python
def list_inbox(
    store, query: InboxQuery | None = None, *, read_actions_enabled: bool = False
) -> InboxPage: ...
```

Actor-ID kommt ausschließlich aus dem tatsächlichen `current_scope`.
Der Service verlangt einen aktiven tatsächlichen `auth.SQLUserStore`, liest
User/Access/Grants frisch aus dessen wirklicher Sessionfactory und vergleicht
den Scope. Rollen-/Origin-/Accesswerte werden nie aus Query/JSON angenommen.
Keine übergebene Principaldataclass autorisiert einen Read.

Vor und nach dem Fachread muss derselbe frische Principal bestehen.
Die jeweilige wirkliche Authconnection und der unabhängige Businesssnapshot
müssen dieselbe persistente SQLitehauptdatei bzw. tatsächliche PostgreSQL-
Server-/Database-/Schemasignatur besitzen. Memory, SQLite-In-Memory oder
getrennte Auth-/Fachdatenquellen: `503 inbox_persistence_unavailable`.
Die Actorread-Session darf nicht die fremde caller-owned Businesssession sein;
sie wird geschlossen, die Businesssession niemals. Kein Stockscanfallback.

Query: Status unread/read/all, optionale exakte Typ-/Severityfilter, Cursor,
Limit 10 (1–100). Requestextras verboten. Persönlicher Readstatus stammt nur
aus der eigenen Paarzeile. Globale read/unread-Zeilen sind aktive Inboxquellen,
archived ist ausgeschlossen. Globalstatus/read_at/B1 bleiben unverändert.

Ein Aggregat liefert full_count und unread_count im selben SQLsnapshot wie
die limit+1-Projektion. unread_count folgt Typ/Severity, ignoriert Status/
Cursor. Chronologie DESC NULLS LAST und byteweises ID-DESC; SQLite CASE
normalisiert nur fehlende Nullfraktion, PG bleibt typisierter DateTime.
Cursor bindet frischen Actor, effektiven Scope, Access/origin, Portfolio-IDs,
Query/Limit/Sort/Version. snapshot_token=null, consistency=live,
actions.mark_all_read=false. Keine stabile Bestandsbehauptung unter Inserts.

Erster Anschluss ist ausdrücklich read-only: alle Itemaktionen melden
`actions.mark_read=false`. Nur Root darf nach tatsächlicher Abnahme des
HTTPwritefence den internen Keywordparameter `read_actions_enabled=True`
setzen. Query/JSON akzeptieren dieses Flag nicht. Es ist ausschließlich
UI-Metadatum und ersetzt niemals den separaten echten CommitAuthoritybeleg.
Explizite Resourcegrants können tatsächlich unlinked Zeilen sichtbar machen;
ein unvollständiges entity_type/entity_id-Paar bleibt für eingeschränkte
Scopes trotzdem unsichtbar. Kein neuer privater Parentgraph wird erfunden.

## Zwingender Rootvertrag für vorbereiteten Einzelread

Im tatsächlich gelesenen Rootstand gibt es keinen nominellen CommitAuthority-
Beleg. `require_fresh_request_authority` ist ein reiner aktueller Credential-
Check; er hält keinen Sessionrowlock bis Commit. Deshalb kein Weak-Fallback.

Root muss ein eigenes Sharedmodul
`backend/services/notification_inbox_commit_authority.py` bereitstellen:

```python
class NotificationReadCommitAuthority:
    # Nur Root stellt diesen konkreten nicht frei konstruierbaren Beleg aus.
    ...

def require_notification_read_authority(
    db: Session, notification_id: str, proof: NotificationReadCommitAuthority
) -> InboxPrincipal:
    # Reale ausgegebene Capability, dieselbe aktive Session/Transaktion/Target;
    # Sid-/Account-/Parentfences leben bis tatsächlichem Commit/Rollback.
    ...
```

Der Verifier muss tatsächliche SQLAuth-/Businessidentität, aktiven Actor,
Access/origin/Grants, echte aktuelle Credential/Sid und native Lockzeugen
prüfen. Kein bool, keine Lambda, keine strukturelle Protocol-Akzeptanz,
kein frei aus JSON/Daten konstruierter `AlreadyChecked`-Stempel. Ein älterer
Beleg einer beendeten Transaktion oder eines anderen Targets ist ungültig.
Root schützt außerdem den tatsächlichen gemeinsamen Scopeparentpfad und
regelt den Abschluss-/Expirycheck vor Commit. Ein Token wird nicht persistiert.

```python
def stage_read(
    db: Session, notification_id: str, *, authority: object
) -> NotificationReadResult: ...
```

Der Domainhelper akzeptiert nominell ausschließlich die konkrete Rootklasse
und ruft den tatsächlichen Rootverifier auf. Ohne Sharedmodul/Beleg: 503/403
vor Inbox-DML. Er vergleicht zusätzlich die reale aktuelle Actor-/Scopebindung,
prüft tatsächliche Eligibility nach dem Authorityfence und insertet das eigene
Paar mit DB-UTC-Zeit und ON CONFLICT DO NOTHING. Die erste Readzeit bleibt
erhalten. Keine Nested-/Neben-Session, kein begin/commit/rollback im Helper,
kein Notificationupdate. Caller besitzt die wirkliche Session/Transaktion.

Das nominelle Rootmodul ist ein zwingender noch fehlender Kompositionspunkt,
keine hier erfundene bereits vorhandene Sicherheitsgarantie. HTTPwrite bleibt
bis Rootimplementierung und echten unabhängigen Nativegates inaktiv.

## Gezielte eigene Tests und ehrliche Beleggrenze

Vorbereitet werden DTO-/Pureimport-/Rawvalidatorregressionen und eigene native
SQLitequellen für echte SQLAccounts/Grants, Mehrbenutzerreads, Scope-/Rolefilter,
Counts oberhalb des Seitenbudgets, native gemischte Zeitfraktionen und Cursor-
Query-/Actorbindung. Authstorefactory auf die eigene synthetische DB setzen
ist erlaubt; `auth.get_user_by_id`/Actorwerte werden nicht durch Mocks ersetzt.
Write-Negativquellen verlangen fehlende/falsche Capability ohne Read-DML.
Positive insert-once/Rollback-/Sid-/Parentraces benötigen anschließend den
tatsächlichen Rootfence; keine Test-Lambda ersetzt ihn und kein Skip gilt als
Abnahme. Quellen werden vorbereitet, in diesem Auftrag noch nicht nativ
ausgeführt. Statische Diffs werden geprüft, reale Gates separat koordiniert.

## Konkreter Korrekturhinweis vor dem Validatorfix

Root hat nach Integration bis `62f138e` den tatsächlichen zwölfteiligen
Pure-/Raw-Gate mit `--noconftest`, hart30s, ausgeführt: 7 PASS / 5 FAIL in
1.43s, normaler Exit1. Roots isolierter Rawfixture-Befund belegt die Ursache:
`set(FIELDS) <= columns` vergleicht Set und Dict und wirft TypeError. Derselbe
Fehler steht im Raw-SQLite- und im SQLAlchemy-Inspectorzweig von `_schema`.

Geplante eng begrenzte Korrektur: an beiden Stellen die tatsächlichen
Spaltennamensets mit `set(FIELDS) <= set(columns)` vergleichen. Alle folgenden
Form-/Nullability-/PK-/FK-/Zeitprüfungen und Testassertions bleiben unverändert.
Die bisher teilweise generische TypeError-Abweisung beweist die negativen
fachlichen Fälle nicht; Root wiederholt deshalb nach Übernahme den ganzen
zwölfteiligen Pure-Gate, anschließend die sechs eigenen SQLitefälle. Hier
kein neuer Runtime-/Import-/App-/DB-/PG-/Teststart und noch kein Fix-PASS.
