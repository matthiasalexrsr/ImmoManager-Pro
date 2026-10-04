# Persönliche Notification-Inbox: Backendvertrag und native Komposition

Stand: 03.10.2026. Vorcodeplan, keine implementierten Endpoints.
Eigener Checkout: `work/dashboard-notification-timestamps`, Basis `0596d69`.
Gelesener Rootstand: `da8eab4471d9bf58e1619933514d9a664fd046d5`;
Frontendentwurf `docs/NOTIFICATION_BELL_INBOX_PLAN_20261003.md` aus `7b3d661`.
Dieses Paket enthält ausschließlich diesen Plan. Keine Imports, Tests,
DB-/Server-/Browserstarts oder PostgreSQL-Änderungen wurden ausgeführt.

Der kleinste erste Release ergänzt genau eine Readstatetabelle, vollständige
SQL-Counts/bounded Live-Seiten und einen persönlichen Einzelread. Mark-all
bleibt bis zur zweiten Komposition deaktiviert: zwei zusätzliche Tabellen
belegen die exakte serverseitige Auswahl, danach verarbeitet eine persönliche
getypte Familie im bestehenden Jobkern diese Mitglieder. Root muss vor den
Writes die tatsächliche Session-/Account-/Parentauthority bis Commit komponieren;
dieser Plan lockert keinen alten Operator, benennt kein neues Migrationhead
und behandelt `l2` weiterhin ausschließlich als TEHA-Reservierung.

## 1. Belegte Ausgangsgrenzen

| Tatsächliche Quelle | Befund und Konsequenz |
| --- | --- |
| `backend/models.py:884–909`, `backend/db/orm_models.py:628–646` | `Notification.status/read_at` gehören dem gemeinsamen Datensatz. Kein persönlicher Read-State, kein `portfolio_id`. |
| `backend/routers/notifications.py:124–150`, `backend/repositories/communication_repo.py:122–143`, `backend/repositories/base.py:201–211` | Die Liste materialisiert über das Repository alle sichtbaren Notifications und filtert/schneidet danach. Der alte Read-Command setzt den globalen Status und committet selbst. Er ist keine atomare persönliche Commandprimitive. |
| `backend/services/portfolio_scope.py:253–318,361–405,605–657` | SQL-Repository und Memorykollektionen besitzen bereits Portfoliofilter. `notification_visible` allein prüft nur Dispatchrollen; daraus folgt **kein** belegter pauschaler Scopeleak der alten Gesamtliste. Eine eigene Engine-Connection benötigt dagegen explizite SQL-Scopes. |
| `backend/services/operational_schedule.py:150–177,539–544`, `backend/db/operational_models.py:44–52` | Dispatchrolle ist eine zusätzliche Sichtbarkeitsbedingung. Die Notification-ID bleibt bei Inhalts-/Severityupdates und Wiederöffnung erhalten; Löschung bleibt ein Dispatchtombstone. |
| `backend/services/dashboard_summary.py:82–88,91–121,176–198,331–345` | B1 hat vollständige SQL-Counts, Dispatchrollenfilter und begrenzte echte Keysetseiten. Seine Ungelesen-Semantik ist weiterhin global. SQLite-ORDER und WHERE verwenden seit dem Fix denselben verlustfreien Zeitstempelkey. |
| `backend/services/tenancy_workflow.py:129–157`, `backend/db/booking_order.py` | Vorhandene signierte, ablaufende und querygebundene Cursor sowie byteweise IDs wiederverwenden. Ein signierter Cursor beweist noch keine unveränderliche Ergebnismenge. |
| `backend/services/checked_publication.py`, `workflow_authority_route.py`, `request_authority.py:26–38` | HTTP-Credential und frischer Scope lassen sich bis zur Veröffentlichung prüfen. Publicationprüfung kann bereits committete Wirkungen nicht zurückrollen. Der reine Revocationcheck hält keinen Sessionlock bis Commit. |
| `backend/services/operational_jobs.py:114–126,197–234,331–365,441–472,639–675` | Der echte Jobkern besitzt native Transaktionen, Claims, Packetbudgets, CAS/Receipts und Wiederaufnahme. Operatorpolicy erlaubt derzeit nur Owner/Verwalter mit installationsweitem Zugriff. Seine MAX-ID-Discovery ist eine obere Sourcegrenze, keine eingefrorene Inboxmitgliedschaft. |
| `backend/middleware.py:215–255`, `backend/services/portfolio_http.py:49–79` | Readonly darf momentan keine Notification-POSTs schreiben; ausgewählte Benutzer dürfen die installationsweiten Operationalroutes nicht verwenden. Persönliche Commands brauchen eng getypte Ausnahmen und eigene Routen, keine generelle Lockerung. |

Die Tabellen-/Spaltenangaben beziehen sich auf diesen Rootstand. Neue Helfer,
Modelle und Schnittstellen unten sind Vorschläge, nicht bereits vorhandene APIs.

## 2. Festgelegte fachliche Semantik

Die neue Inbox ist additiv. Alte Notification-GET/CRUD/Readrouten, gemeinsame
`status/read_at` und B1-Counts behalten ihren Vertrag. Ein späterer B1-Wechsel
auf persönliche Reads wäre eine eigene ausdrücklich freigegebene Komposition.

Aktiv sind Notifications mit gemeinsamem Status `unread` **oder** `read`;
`archived` ist aus dieser Inbox ausgeschlossen. Persönlich gelesen ist genau
ein vorhandener Datensatz für das Paar Actor/Notification. Keine Readzeile
bedeutet persönlich ungelesen. Historisches globales `read_at` belegt keinen
bestimmten Leser und wird niemals für Benutzer nachgefüllt.

Der Read gilt für die Notification-ID. Ein Update oder Wiederöffnen derselben
ID nimmt den persönlichen Read nicht zurück. Wer fachlich ein neues Ereignis
zustellen möchte, benötigt eine neue Notification-ID. Dieser kleine Vertrag
passt zur vorhandenen Wiederverwendungssemantik und vermeidet erfundene
Publikationsrevisionen.

Alle aktiven Benutzer, einschließlich `readonly` und ausgewählter Portfolios,
dürfen ausschließlich ihre eigenen berechtigten Notifications lesen und als
gelesen markieren. Benutzer-, Rollen-, Portfolio- oder Jobactorwerte aus JSON
sind verboten. Persönliche Reads erlauben kein allgemeines Communication-CRUD.

V1 setzt ein persistentes SQLite-/PostgreSQL-Backend mit tatsächlichem
SQL-Authstore in derselben physischen Datenbank voraus. Das ist eine explizite
Kompositionsbedingung für FKs und CommitAuthority, kein stiller Zugriff auf eine
andere Default-DB. Memory oder getrennte Auth-/Fachdatenbanken erhalten
`503 inbox_persistence_unavailable`, bis ein gesondert belegter Adapter besteht.
Kein Fallback auf `list_notifications()`, kein RAM-Stockscan, kein Fake-Count.
Die Glocke muss diesen Zustand neutral als nicht verfügbar darstellen.

### Berechtigter Grundbestand

Ein gemeinsamer SQL-Eligibilitybuilder wird für Seiten, beide Counts,
Einzel-Read, Auswahlvorbereitung und jeden Jobpacket verwendet:

1. tatsächlicher aktiver Actor, ausdrücklicher Scope; `scope=None` bedeutet
   hier nie installationsweiten Zugriff;
2. aktive gemeinsame Notification;
3. `scoped_clause(NotificationORM, scope=actual_scope)` einschließlich echter
   Parents/Resource-Portfoliobindungen;
4. dieselbe Dispatchrollenregel wie B1, per `NOT EXISTS` statt N+1-Lookups;
5. persönliche Readbedingung per actor-gebundenem `EXISTS/NOT EXISTS`.

Bei eingeschränkten Benutzern bleiben unbekannte, unvollständige oder nicht
auflösbare private Entityreferenzen verborgen. Parentauflösung verwendet den
tatsächlichen Referenzkatalog/Scopegraph, keine Payload-Portfolio-ID und keine
frei erfundene zweite Aliasliste. `entity_id=None` allein ist kein
Globalitätsbeleg: unverbundene Altzeilen gehören laut bestehendem Scopegraph
zur Installation; ausgewählten Benutzern hilft nur ihre tatsächliche explizite
Resource-Portfoliobindung. Der Frontendentwurf muss seine Globalregel so
präzisieren. Bewusst globale neue Zustellung wäre erst mit einem eigenen
vertrauenswürdigen serverseitigen Audiencevertrag zulässig; nicht Teil V1.

Unsichtbare Einzel-ID: neutrales 404. Gesamtcounts, Seiten und Fehler enthalten
keine Anzahl oder Details fremder Rollen/Portfolios/Benutzer.

## 3. Phase A: vollständige persönliche Live-Inbox und Einzel-Read

### GET /api/v1/notifications/inbox

Query: `status=unread|read|all` (default `unread`), optional
`notification_type` und `severity`, `after`, `limit=10` (1–100).
Die Grenze betrifft nur die Seite. Es gibt kein Stock-/Gesamtlimit.

`NotificationInboxPageV1`:

```json
{
  "items": [],
  "full_count": 137,
  "unread_count": 137,
  "has_more": true,
  "next_cursor": "...",
  "snapshot_token": null,
  "consistency": "live",
  "actions": {"mark_all_read": false}
}
```

`full_count` zählt den gesamten berechtigten Bestand mit Status/Typ/Severity.
`unread_count` zählt denselben Typ-/Severitybestand persönlich ungelesen,
unabhängig von Statusfilter, Seite und Cursor. Bei Live-`status=unread` sind
beide Counts gleich. Die globale Glocke fragt ohne Typ-/Severityfilter ab;
dort ist `unread_count` ihr vollständiger persönlicher Badgecount. Gefilterte
Abfragen dürfen keinen globalen Badge ersetzen. Diese Präzisierung löst die
im Frontendentwurf sonst widersprüchliche Filter-/Countaussage.

Item: ausschließlich `id, notification_type, title, content, severity,
entity_type, entity_id, created_at, read_at, actions.mark_read`. `read_at`
stammt nur aus der eigenen Readzeile. Keine fremden Readzeilen, Dispatchdetails,
verdeckten Parentpayloads oder aktuellen Userprofile.

Zwei Aggregate und die begrenzte `limit+1`-Projektion stammen aus derselben
kurzen unabhängigen Readsnapshot-Connection; vorhandenes
`booking_export._snapshot` liefert tatsächliches SQLite-BEGIN bzw.
PostgreSQL-REPEATABLE-READ/READ-ONLY. Kein ORM-Autoflush/Identitymap-Resultat,
kein GET-Fach-DML und keine nachgelagerte Python-Scopefilterung. Auth-eigene
Last-used-Verwaltung ist davon getrennt.

Reihenfolge: `created_at DESC NULLS LAST, bytewise(id) DESC`. WHERE und ORDER
benutzen **denselben** Key. Für SQLite:
`CASE WHEN length(CAST(created_at AS String))=19 THEN raw||'.000000' ELSE raw END`;
Cursorzeit mit Space und genau sechs Nachkommastellen. PostgreSQL bleibt
DateTime. Keine Mikrosekundenkürzung oder Bestandsmigration. Legacy-NULLs werden
erreicht. Eine gemeinsame kleine Chronologieprimitive ist gegenüber Copy/Paste
in B1/Inbox vorzuziehen; ihre Auslagerung ist Root-Sharedownership.

Cursorbinding: Kind/Version, tatsächliche User-ID/Rolle, effektiver Scope,
rohes `portfolio_access`, `portfolio_access_origin`, sortierte Portfolio-IDs,
Typ/Severity/Status, Limit, Sortprofil, Konsistenzmodus und ggf. Auswahl-ID/
Digest/Epoch. Diese Rohwerte fehlen teilweise in `AccessScope`; sie müssen
frisch aus tatsächlichem User/Access/Grantbestand kommen. Cursor nach
Grant-/Origin-/Querywechsel: bestehendes neutrales 422; keine stille Fortsetzung.
Aktuelle fehlende Authority: 401/403. Kein HMAC-/Cursorzweitsystem.

Live-Keyset verspricht keine feste Mitgliedschaft unter parallelen
Neuzugängen/Änderungen. Neue Same-Sekunde-IDs unterhalb des Cursors können auf
einer Folgeseite sichtbar werden. Die UI darf diesen Modus weder als geprüften
Mark-all-Snapshot noch als eingefrorene Inbox bezeichnen. Neue Abfrage der
ersten Seite aktualisiert den Livebestand.

### POST /api/v1/notifications/inbox/{notification_id}/read

Leerer Body; keine Actor-/Status-/Zeitstempelfelder. Sichtbarkeit frisch
prüfen, nur eigene Readzeile mit DB-Zeit einfügen. Unique-Paar plus
dialektsicheres `ON CONFLICT DO NOTHING` macht den Command idempotent und
erhält den ersten tatsächlichen `read_at`. Kein Update der Notification,
kein Commit im Domainhelper, keine `CommunicationRepository.mark_notification_read`.

Response 200: `{notification_id, read_at}`. Anschließend lädt die UI die
Live-Inbox neu; sie zieht keinen lokalen Fake-`1` vom Badge ab. Das ist die im
Frontendplan zulässige GET-Refreshvariante und erspart einen Count außerhalb
derselben belegten Querybindung. Fehlender/verborgener/archivierter Target: 404.

## 4. Phase B: exakte Read-Auswahl statt Timestamp-/UUID-Pseudosnapshot

Phase A lässt Mark-all bewusst inaktiv. Phase B ergänzt eine vorbereitete
serverseitige Auswahl. Dadurch legt jeder 60-s-Badgepoll **keine** komplette
Bestandskopie an und ein Read-GET erzeugt keine Journalzeilen.

### POST /api/v1/notifications/inbox/read-selections

Body mit `extra=forbid`: `idempotency_key` sowie optional
`notification_type, severity`; stets persönlich ungelesener Bestand.
Vorbereitung geschieht erst auf ausdrückliche Mark-all-Interaktion.

Innerhalb einer tatsächlichen nativen Transaktion werden alle zu einem
belegten SQL-Readstand berechtigten ungelesenen IDs mit `INSERT ... SELECT`
in die Auswahl geschrieben. Die Rolle-/Parent-/Readbedingungen stehen
**im SELECT**, nicht nach dessen Materialisierung. Ein SQL-Statementcapture
bestimmt die vollständige Mitgliedschaft, nicht eine Reihe späterer Live-
Seiten. Danach werden tatsächliche gespeicherte Mitglieder mit geschlossenem
Stream/fetchmany gehasht und gezählt, der Header wird atomar versiegelt.
Keine Pythonliste sämtlicher IDs, keine Client-IDliste, kein Countlimit.
Fehler/Timeout vor Commit: Rollback, kein Token und keine Teil-Auswahl.

Response 201 (Replay 200): `{selection_id, snapshot_token, selected_count,
captured_at, expires_at}`. V1-Auswahltoken gilt 15 Minuten ab tatsächlichem
Capture; der Datenbankwert, nicht die allgemeine Cursorlaufzeit, entscheidet.
Die UI zeigt den neuen überprüfbaren
Auswahlcount, bevor sie den Command bestätigt. Der vorherige Livecount ist
kein Beleg für diese vorbereitete Auswahl.

Auswahlpreviews benutzen GET /inbox mit zusätzlichem `snapshot_token`,
gleicher Querybindung, `status=unread` und `consistency="selection"`; abweichender
Status/Typ/Severity wird abgewiesen. Seiten sind auf die
versiegelten IDs beschränkt und erneut aktuell autorisiert. Ihr
`full_count` betrifft nur die weiterhin berechtigte Auswahl und den
aktuellen Readstatus; `unread_count` bleibt der vollständige **Live**-Count
derselben Typ-/Severityfilter, damit neu eingetroffene Einträge im Badge
bleiben. Ergänzend `selection_count` = unveränderlicher ursprünglicher
Auswahlcount. Die Gleichheit beider Counts gilt nur im Live-Unreadmodus.
`actions.mark_all_read` ist nur bei gültiger eigener versiegelter, noch nicht
an einen Job gebundener Auswahl true.

Token verwendet die vorhandene signierte Cursorprimitive mit eigener
Kindbindung und Position Auswahl-ID/Digest/Authority-Epoch. Das serverseitige
Ablaufdatum ist zusätzlich verbindlich, auch wenn der allgemeine Cursor länger
lebt. Token enthält keine Titel, Credentials oder große Mitgliedsliste.
Jede Verwendung prüft tatsächlichen Header/Actor/Scope/Filter und Seal.
Ein anderer Actor erhält 404; ungültiger eigener Auswahlkontext 409 bzw.
ungültige Signatur 422. Ein Token ist kein Authersatz.

### Warum nicht MAX(created_at)/MAX(id)/nextval?

Ein späterer INSERT mit derselben SQLite-Sekunde und kleinerer zufälliger ID
würde bei solchen Grenzprädikaten in eine angeblich alte Auswahl fallen.
Auch eine PostgreSQL-`nextval` vor Commit bietet ohne Writerbarriere keine
Commitreihenfolge. Die vorhandene Job-`upper`-Logik darf daher nur über die
bereits **versiegelten Mitgliedszeilen** laufen. Neue Notifications, auch mit
zurückdatiertem Zeitstempel oder kleinerer UUID, sind keine Mitglieder.

Ein gemeinsam bis Commit gesperrter Publikationszähler wäre eine andere
Architektur, benötigt aber sämtliche Notificationwriter und native
Insertguards. Er ist nicht heimlich Teil dieses kleineren Inboxpakets.

Capture benötigt O(N) DB-Schreibarbeit und O(N) Hash-I/O für N Mitglieder;
es ist keine konstante Operation. Der SQL-Capture und sein Streamingabschluss
haben ein gemessenes Gesamtdauer-/Lockbudget; dessen Überschreitung liefert
retryfähiges 503 und Rollback, niemals eine verkürzt als vollständig bezeichnete
Auswahl. 100.001-/großer synthetischer Capture samt Speicher-/WAL-/Locknachweis
ist vor breiter Phase-B-Freigabe erforderlich. Die Packetwiederaufnahme ersetzt
diesen Capturebeleg nicht. Sehr große Bestände jenseits dieses nativen Budgets
benötigen später den ausdrücklich gemeinsam geänderten Publikationszähler,
nicht ein heimliches Gesamtlmit oder best-effort-Snapshot.

## 5. Phase C: Mark-all als eigene getypte Familie im bestehenden Jobkern

### POST /api/v1/notifications/inbox/mark-all-read

Body: `{snapshot_token, idempotency_key}`, `extra=forbid`.
Nur eine eigene versiegelte, nicht abgelaufene Auswahl mit unveränderter
tatsächlicher Principal-/Querybindung kann einen neuen Job erzeugen.

Immer 202 mit eigener getypter Jobansicht:
`{job_id, state, selected_count, processed_count, marked_count,
already_read_count, skipped_count, next_action}`.
Keine Behauptung `marked_count=selected_count` vor tatsächlicher Verarbeitung,
kein `unread_count=0` als Startbestätigung, keine synchrone Massenschleife.
Badge kommt weiterhin aus einem frischen Live-GET.

Erforderlicher Rootadapter des bestehenden Jobkerns:

- neue ausschließlich interne Familie `notification_read` mit expliziter
  Semantikversion 4 und eigenem Parameter-DTOvertrag; bisheriger öffentlicher
  `JobCreate` und seine bisherigen Literal-Familien bleiben unverändert;
- persönliche Operatorpolicy nur für diesen typisierten Parameterzweig:
  frischer aktiver eigener Actor, ausgewählter Scope/readonly zulässig;
  alle vorhandenen Operationalfamilien behalten ihre breite Operatorpolicy;
- Parameter: `kind, semantics_version, selection_id, selection_hash,
  principal_binding, filters, families=["notification_read"]`, niemals Token;
  kanonischer Requesthash, Actor/Keyunique und Konflikt-/Replayprüfung bleiben
  beim vorhandenen Journal, zusätzlich Auswahl→genau ein Job;
- Discovery ausschließlich gespeicherte Auswahlmitglieder: deren unveränderliche
  IDs nach byteweiser Ordnung; `upper` ist hier deren echter Maxkey;
- `source_id` = Mitglieds-Notification-ID, `planned_revision` =
  kanonischer Mitgliedsdigest. Keine heutige Notificationversion als
  angebliches Original der damaligen Mitgliedschaft;
- Apply in bestehender Unit: tatsächliche Notification/Parents/Dispatch erneut
  prüfen, eigene Readzeile insert-once; legitime Outcomes `marked`,
  `already_read`, `deleted_or_archived`, `no_longer_visible`;
  keine Titel/verborgenen Entitydetails im Ergebnis. Native Lanecounter bleiben
  kompatibel: `created=marked`, `updated=0`, `skipped=already_read/gone/hidden`;
  adapterseitiger Rückgabewert ist `created` oder `skipped`, genauer Outcome
  steht im getypten Result. `scanned` zählt entdeckte Mitglieder, nicht fertige
  Writes; UI-`processed_count` und Outcome-Untercounts kommen aus tatsächlichen
  done-Items per SQL-Aggregat, nicht aus einer gleichgesetzten Scananzahl;
- Readzeile, Workitemoutcome, Lane-/Jobfortschritt und Abschlussclaimfence
  committen gemeinsam. Fehlgeschlagene Packets schreiben keinen Fortschritt;
  abgegrenzte frühere erfolgreiche Packets bleiben ehrlich sichtbar;
- kein neuer Scheduler, keine Extraqueue. Bestehende Continue/Lease/CAS/
  Retry/Cancel-Primitive mit `PacketPolicy` verwenden.

Neue eigene Inbox-Jobrouten: GET `/inbox/read-jobs/{job_id}`,
POST `.../{job_id}/continue` mit vorhandenem `JobContinue`,
POST `.../{job_id}/cancel` und `.../{job_id}/retry` mit vorhandenem
`JobCommand`. Kein persönlicher Zugriff auf
`/tasks/operational-jobs` und keine Offenlegung fremder Workitemlisten.
Continue benötigt echte aktuelle Requestauthority; Browser/Caller stößt
begrenzte Packets an. Unbeaufsichtigte Fortsetzung nach Ende der Session ist
keine ererbte Berechtigung und gehört nicht zu dieser Phase.

Gleicher Actor/Key und identischer Request: ursprünglicher Job/Receipt;
anderer Request oder anderer Auswahlbezug: 409, kein zweiter Job.
Gleiche Auswahl mit anderem Key: 409 `selection_already_claimed`, kein
erfundener zweiter Commandbeleg. Anderer Actor kann keinen eigenen Replay
unter fremdem Token erhalten. Bestehende akzeptierte Replays bleiben nach
Tokenablauf als eigene Jobansicht lesbar, erzeugen aber keine neue Wirkung.
Grant-/Originwechsel blockiert weitere Packets; keine automatische
Auswahlverbreiterung. Neue Auswahl ist eine neue ausdrückliche Aktion.

## 6. Modell- und Migrationsvertrag, noch ohne Revision

Vorgeschlagene eigene Quellen:

| Datei | Konkreter Inhalt |
| --- | --- |
| `backend/services/notification_inbox_types.py` | Reine Query-, Page-, Item-, Readresult-, Selection- und PersonalJob-DTOverträge, strikte Bodies, kanonischer Principal-/Filter-/Mitgliedsvertrag. |
| `backend/services/notification_inbox.py` | SQL-Eligibility, Counts/bounded Seiten, transaction-only Einzel-Read und Selectioncapture. Keine Authstorefactory, kein Repositorycommit. |
| `backend/services/notification_read_jobs.py` | Kleine Source-/Applyadapter zur bestehenden Jobunit, keine zweite Atomic-/Lease-/Queueimplementierung. |
| `backend/db/notification_inbox_models.py` | Readmodell und separate Selectionfamilie; frühe Metadatenregistrierung ausschließlich durch Root. |
| `backend/db/notification_inbox_schema.py` | Reine strukturelle Prüfung und ausdrücklich aufgerufene native Guardinstallation; kein Import-DDL oder Runtimeautorepair. |
| `backend/services/notification_inbox_validation.py` | Raw-SQLite/SQLAlchemy-Connectionvalidator, streamend, ohne Auth/Settings/Dependencies/App/Storeimports. |
| `backend/routers/notification_inbox.py` | Später Rootintegrierte additive `WorkflowAuthorityRoute`; statische /inbox-Routen vor altem /{id} registrieren. |

Domainhelper-Signaturen (intern, noch nicht vorhanden):

```python
def list_inbox(store, query: InboxQuery, *, principal: InboxPrincipal) -> InboxPage: ...
def stage_read(unit, notification_id: str, *, principal: InboxPrincipal) -> ReadResult: ...
def stage_selection(unit, request: SelectionCreate, *, principal: InboxPrincipal) -> ReadSelection: ...
def discover_read_members(unit, job, lane, *, width: int, deadline: float) -> None: ...
def apply_read_member(unit, job, lane, item, *, principal: InboxPrincipal) -> tuple[str, dict]: ...
def validate_notification_inbox_database(connection, *, deadline=None) -> bool: ...
```

`unit` ist die tatsächlich Rootautorisierte vorhandene Job-Writeunit bzw. ein
Rootadapter derselben nativen Transaktionsprimitive. Domainhelper flushen,
committieren/eröffnen jedoch keine Neben-Session. Der Router veröffentlicht
erst nach dem äußeren Commit. Principal wird intern aus realem Authbestand
gebaut; weder `actor_id=None` noch eine System-/Clientidentität wird geraten.

### Readfamily (Phase A)

`notification_read_states`:
PK `(actor_id, notification_id)`, `read_at NOT NULL`;
FK `actor_id -> users.id ON DELETE CASCADE`,
FK `notification_id -> notifications.id ON DELETE CASCADE`.
Persistente erste Readzeit, nur insert-once. Keine unveränderliche finanzielle
Originalfamilie. Löschen des gemeinsamen Notifications oder des Accounts
entfernt den aktuellen eigenen Readstate; keine Wirkung auf andere Paare.

### Selectionfamily (Phase B/C)

`notification_read_selections`:
UUID-ID, Actor-ID, hashed Createkey, Request-/Principal-/Filterdigest,
versionierte minimale Filter-/Principaloriginale, Capture-/Expiryzeit,
versiegelter `member_count/member_hash`, State, Authority-Epoch, optional
eindeutiger `job_id` mit RESTRICT-Jobreferenz. Unique Actor/Createkey und
eindeutiger Jobbezug. Historischer Actor String bleibt wie bei Operationaljobs
als Nachweis erhalten; keine Actor-FK-Cascade, die angenommene Jobbelege löscht.

`notification_read_selection_members`:
PK `(selection_id, notification_id)`, Selection-FK RESTRICT,
kanonischer nullable Capture-Sortkey und minimale damalige
`entity_type/entity_id` als Referenznachweis. Keine Titel/Contents/Userprofile.
Notification-ID bleibt eine weiche historische Referenz: keine FK-RESTRICT-
Sperre gewöhnlicher Notificationlöschung und keine Cascade, die eine
versiegelte Auswahl heimlich verkürzt.

Headeroriginal, Count/Digest und Mitgliedsidentitäten sind nach Seal nativ
gegen INSERT/UPDATE/DELETE geschützt; nur klar abgegrenzte Lifecyclefelder
(State/Epoch/Jobbindung) haben kontrollierte CAS-Transitions. Seal erlaubt
keine nachträgliche Mitgliederergänzung. Jobbindung prüft denselben Digest.
State/Epoch/Jobbindung sind ausdrücklich außerhalb des Originaldigests;
Restoreepoch-Wechsel schreibt keine eingefrorenen Originalfelder um.
Der Digest verwendet versionierten kanonischen Header und tatsächliche
Mitglieder in byteweiser ID-Reihenfolge mit längengerahmten UTF-8-Records.
Kein `list(all_members)`; tatsächliche Count-/Hashprüfung aus Stream.
Hashes sind Integritäts-/Referenzbelege; sie beweisen keine Authentizität einer
vollständig fremd neu geschriebenen Datenbank.

Die beiden Schemafamilien werden separat versioniert: vollständige alte Images
dürfen beide gar nicht besitzen; Phase-A-Images dürfen Readstate ohne beide
Selectiontabellen besitzen. Eine halbe Selectionfamilie, fehlende Spalten/
PKs/Unique/FKs/Guardteile oder Jobversion4 ohne vollständige Selectionfamilie
ist beschädigt und wird vor jeder DDL/DML abgewiesen. Kein `create_all` als
stilles Reparieren einer teilweisen Familie.

Read-PK unterstützt Actor-EXISTS. Relevante Selectionindexes:
`(actor_id, created_at, id)`, Expiry/Lifecycle, Mitglieder
`(selection_id, created_sort_key DESC, notification_id DESC)` bzw. byteweise
ID-Discovery. Notification-Ordnung braucht gemessene PG-/SQLite-Pläne:
auf SQLite nutzt der CASE-Ausdruck keinen bloßen DateTimeindex vollständig;
passender Expressionindex nach Rootfreigabe prüfen. Das betrifft DB-Sortkosten,
nicht RAM-Materialisierung oder Scopekorrektheit. Kein Indexobjekt aus
Migrationen an globale Metadaten hängen; explizites `op.create_index`.

Root koordiniert Migration-ID, tatsächliches `down_revision` und Singlehead.
Im gelesenen Rootbaum endet die sichtbare Folge bei `k2→j2`; `l2` ist
ausdrücklich TEHA vorbehalten. Dieser Plan reserviert **keine** Revision.
A und B/C sind getrennte kleine Releases mit sequenziell koordinierten
Revisionen, oder ein Rootentschiedener gemeinsamer DDLstand mit deaktivierter
Phase B/C. Es wird kein Parallelhead angelegt.

## 7. CommitAuthority: notwendige Rootkomposition

GET benötigt tatsächliches `require_auth`, frische vollständige Principalwerte
vor SQL und eine erneute Credential-/Grantprüfung unmittelbar vor Headers
für **alle** Rollen, auch all/Owner. `WorkflowAuthorityRoute` und
CheckedPublication sind die vorhandene Basis; Cursorbinding erweitert deren
heute nur effektiven `AccessScope` um rohe Access/Originwerte.

Write/Selectioncapture/Jobpacket benötigen zusätzlich eine native Authority-
Grenze bis zum **tatsächlichen Commit**. Accountmanagementrowbarriere
(`auth.SQLUserStore._lock_management`, `backend/auth.py:859–872`) schützt
gegen Rollen-/Grant-/Aktivitätsänderungen. Sie ist allein keine Sessionbarriere:
`auth_sessions.revoke_own/revoke_from_token` sperren die tatsächliche
Sessionrow, nicht diesen Managementmarker. Das heutige
`require_fresh_request_authority` prüft Revocation über eine unabhängige
Readtransaktion. Ein letzter Check allein ist ein PG-TOCTOU-Fenster.

Root muss daher den vorhandenen gemeinsamen Authoritypfad getypt ergänzen:
tatsächliche signierte Accesscredential mit Session-ID, realer Sessiondatensatz
und aktive User/Grantzeilen; geeigneter Sessionrowlock bis Domaincommit,
dazu ein konsistenter geprüfter Lockorder mit bestehenden Rotation/Revoke/
Accountpfaden. SQLite zuerst wirkliche Writerbarriere; keine zweite Session-
Last-used-Schreibtransaktion im Domainwriter. PostgreSQL braucht einen
Lockmodus, der die Revocation-UPDATE tatsächlich serialisiert. Scope- und
Credentialablauf vor dem Abschluss erneut prüfen. Rawtokens nie persistieren.

Für Einzelread und begrenztes Applypacket ist außerdem der tatsächliche
Notification-/Dispatch-/Parentpfad bis Commit abzusichern: reale Zielrow und
die für den Scope verwendeten Parent-/Resourcegrantzeugen in gemeinsam
geprüfter Reihenfolge sperren und Eligibility **nach** dem Erwerb nochmals
prüfen. Bei Tenant-EXISTS gehört der tatsächlich sichtbare Contractzeuge dazu.
Eine neue generische Lockgraphfunktion existiert hier noch nicht; Root muss
den Adapter mit vorhandenen Location-/Contract-/Privacywritergrenzen komponieren,
statt allein auf einen ungesperrten Eligibilitycheck zu vertrauen. Kein
installsweiter Parentstocklock. Selectioncapture belegt dagegen ausdrücklich
die Mitgliedschaft seines einzelnen SQL-Readstands; sein Statementcapture ist
kein Versprechen, alle Domainparents des gesamten N-Bestands bis Commit zu
sperren. Spätere Applys prüfen diese Targets erneut.

V1 persönliche Writes setzen diesen tatsächlichen Sessionfamilienbeleg voraus.
Ein alter Access-token ohne `sid` benötigt vor dieser neuen Aktion eine echte
erneute Anmeldung; keine erfundene Familie/Legacy-blacklist-Commitgarantie.
Read-only GET kann weiterhin die vorhandene echte Legacy-Authprüfung nutzen.
Direkte Domainaufrufe brauchen einen ausdrücklichen intern frisch autorisierten
Principal, keine HTTP-/Scope-/Actoroverride-Testmocks.

Native Raceabnahme muss die echte Linearisation prüfen: gewinnt Revoke/Grant-
change zuerst, keine Wirkung; hält der Command seine native Barriere bereits,
darf der Änderer erst nach seinem Commit gewinnen. Kein künstlicher Test,
der trotz gehaltenem Sessionlock einen Revokecommit während der Sperre
behauptet. Ablauf/Fehler nach erstem Domain-DML rollt das ganze aktuelle
Packet samt Read/Progress zurück. Zwischen Packets darf eine echte Revocation
neue Wirkungen vollständig stoppen.

Nötige Rootstellen: `auth.py`, `services/auth_sessions.py`,
`services/request_authority.py`, gemeinsame Job-Authority/Atomicpolicy,
`middleware.py`, `services/portfolio_http.py`, `routing.py`.
Persönliche RBAC-Ausnahme nur für konkrete neue POST-Pfade und die eigenen
Readjobcommands; keine Prefix-Ausnahme für allgemeine Notificationwrites.
Diese Sharedänderungen sind nicht Eigentum dieses Analysepakets.

## 8. Restore, Retention, Referenzen und Privacy

Rootregistrierung konkret:

- `backend/db/session.py`: frühe Modellimports, getrennte Familyprüfung
  **vor** Fresh-DDL, explizite dev/test-Guardinstallation;
- `backend/db/migrations/env.py`: Metadatenregistrierung; tatsächliche native
  Upgrade-/Downgradefolge und Schadenprüfung;
- `backend/db/runtime_schema.py`: Singlehead, tatsächliche Tabellen/Spalten/
  Keys/Guards read-only prüfen; niemals nachinstallieren;
- `backend/services/portfolio_scope.py`: neue interne Tabellen nur mit
  verbindlicher eigener Actor-/Selection-/Jobpredicate. Aufnahme in
  `INTERNAL` alleine gewährt keine sichere Serviceautorisierung;
- `backend/services/operational_job_types.py`, `operational_jobs.py`,
  `operational_job_validation.py`: persönlicher typisierter Parameterzweig,
  Familyadapter/Operatorpolicy, Restorevalidation. Bestehende Semantikversionen
  1–3 bleiben byte-/verhaltenskompatibel;
- `backend/services/full_recovery.py:206–255`,
  `recovery_validation.py:248–257`,
  `recovery_sessions.py:70–81,142–147`: neuen reinen Validator vor
  Pathrewrite, Claimreset, Sessioninvalidate und sämtlichem Restore-DML
  aufrufen; vollständige alte Schemaabwesenheit ausdrücklich zulassen;
- `backend/services/recovery_retained.py`: getypte Resetklassifikation,
  Parent-/Notificationbezüge und Native-Writebarriere. Reads sind löschbare
  eigene Metadaten; angenommene Selection/Jobs/Receipts sind retained
  Commandbelege. Kein pauschales Aufnehmen aller Reads in eine finanzielle
  Originallöschsperre;
- tatsächliche Referenzstellen im gelesenen Baum:
  `backend/services/portfolio_scope.py:100–146` (Entityaliases/Textparents),
  deklarierte Model-FKs und die getypten Journal-/Retainedvalidatoren.
  Rootregistrierung ergänzt aktuelle Read-FKs, weiche historische
  Mitglieder-Entity-/Notificationrefs und Job-/Selectionrefs einzeln.
  `portfolio_references.py` ist tatsächlich nur der CSV-Parentcompiler;
  diese Tabellen besitzen keine CSV-References und brauchen dort keine
  erfundene Registration. Der Filekatalog in `recovery_validation.py` ist
  ebenfalls kein Notification-IDkatalog. Eine historische fehlende
  Notification ist ein legitimer Skip, kein restaurierter Ersatz;
- `backend/services/tenant_retained_graph.py:411–492`,
  `tenant_privacy.py`: persönliche Jobfamilie/Effecttyp explizit behandeln.
  Heutige Jobsubjectregeln erkennen sie noch nicht. Nur tatsächliche belegte
  Tenant-/Contract-/Entityreferenzen exportieren; keine gesamte Auswahl eines
  Actors in einen Tenantexport kopieren. Private Reader-/Scope-/Filterwerte
  anderer Benutzer sind nicht automatisch Tenantdaten.

Reiner Validator (raw SQLite oder SQLAlchemy-Connection, mit Deadline):
separate all-absent/partial-Familyprüfung, Readpaare/FKs/erste Zeitformen,
Header-/Membercount und Streamdigest, zulässige Lifecycle/CAS-/Zeitformen,
eindeutige Actorkeys und Auswahl→Jobbindung, Version4-Requesthash/Family/
Membersource-/Workitem-/Outcomebelege, Counter-/Exhausted-/Claimparität.
Kein Auth/Config/App/Dependencies/Storageimport und kein Validator-DML.
Historische Scope-/Actororiginale gegen ihren damaligen Vertrag validieren,
nicht mit heutigen Grants oder heutigen Notificationinhalten rückprojizieren.

Readstates bleiben beim Restore erhalten. Vergangene angenommene Jobs und
ihre genaue Mitgliedschaft bleiben nachvollziehbar. Vor Invalidation erst
alle Original-/Journalfamilien beweisen, dann in derselben äußeren
Restoretransaktion Claims zurücksetzen, öffentliche Auswahl-Epochs entwerten
und Sessions widerrufen. Ein altes signiertes Snapshottoken darf nach Restore
nicht wieder neue Wirkungen eröffnen. Bereits angenommene Jobs dürfen nur
nach neuer tatsächlicher Auth und eigener unveränderter Scopebindung
ausdrücklich weitergeführt werden; keine automatische Publikation.

Allgemeine Reset-/Demo-/Importpfade dürfen keine Notificationbasis entfernen
und einen aktiven Auswahl-/Jobbeleg als scheinbar vollständig stehen lassen.
Gewöhnliche einzelne Notificationlöschung darf dagegen die aktuelle Readzeile
cascadieren; das historische Mitglied bleibt als gelöschter Target nachweisbar.

TTL ist kein Bestandslimit: ungebundene abgelaufene Auswahlen können später
durch einen getypten bounded Maintenancepfad im bestehenden Jobkern entsorgt
werden. Angenommene Jobauswahlen/Receipts werden damit nie mitgelöscht.
Native Seal-/Lifecycleguards müssen diesen konkreten autorisierten Cleanup
unterscheiden; kein allgemeiner Triggerdisable-/Deleteall-Schalter.
Retentiondauer und Cleanupvertrag sind Rootfreigabegates vor breiter
Selectionnutzung. Phase A benötigt keine Selectionkopien/solchen Cleanup.

## 9. Native Abnahme, erst nach separat koordinierter Slotfreigabe

Geplante eigene Regressionen:
`backend/tests/test_notification_inbox.py`,
`test_notification_inbox_authority.py`,
`test_notification_inbox_postgres.py`,
`test_notification_read_selections.py`,
`test_notification_read_jobs.py`,
`test_notification_inbox_validation.py`,
`test_notification_inbox_migration.py`.
Root ergänzt zentrale Restore-/Retention-/CLI-/UI-Komposition.

1. Echte SQLite-/PG-Notificationwriter und echte SQLAuthaccounts/-Sessions:
   zwei Benutzer derselben Role/Grants, A read, B weiterhin ungelesen;
   globaler Altstatus/read_at und B1 unverändert. Readonly/selected eigenes
   Read erlaubt, allgemeines Notification-CRUD weiter verboten.
2. SQL-FullCounts bei 100.001 berechtigten Einträgen und Seite 10; zusätzliche
   fremde Rollen/Portfolios zählen nie. SQLtrace beweist Scope vor LIMIT;
   Store-Stockliste/ORM-all explizit verboten. Begrenzte Projektion und
   serverseitiger Stream, keine künstliche Test-/Produktstockgrenze.
3. Gemischte echte SQLite CURRENT_TIMESTAMP- und SA-Zerofraktionszeilen,
   1-Mikrosekundenunterschied, gleiche Sekunden/IDs, Legacy-NULL; sämtliche
   berechtigten OriginalIDs genau erreichbar. PostgreSQL DateTimeparität
   und vorhandene B1-Keysetregressionen unverändert.
4. Opaque/manipulierter/abgelaufener Cursor, anderer Actor, Filter/Limit/
   Accessorigin/Grantwechsel. Tatsächlicher Parentmove, kaputte Entityreferenz,
   unbekannter Entitytyp, ungebundene Legacyzeile, Resource-Portfoliogrant,
   Rolle/Dispatchänderung: Seiten und Counts dieselbe Eligibility, hiddenID404.
5. Auswahlcapture über mehr als Packet-/Seitengröße. Nach Seal tatsächliche
   spätere Notification mit identischer Sekunde und ID sowohl kleiner als auch
   größer als vorhandene Cursor/Upper-ID, zusätzlich Rückdatierung:
   niemals Mitglied/Read durch den alten Mark-all-Job.
6. Zwei unabhängige native Commands/Verbindungen: Einzelread insert-once,
   gleicher Actor/Key Replay, Konflikt bei anderem Request; andere Actoren,
   gleiche Auswahl/zweiter Key, abgelaufener Token und akzeptiertes Replay.
   Fehler nach erstem Domain-DML rollt Read, Selection, Job und Fortschritt
   vollständig zurück. Keine Actor-/Scopeoverride-Mocks.
7. Nativer Jobpacket-/Crash-/Restartbeleg mit mehr als 64 Targets, Claimlease
   läuft ab, frischer Worker gewinnt, alter Fence publiziert nichts.
   Schon gelesene/gelöschte/archivierte/verschobene Targets liefern korrekte
   getypte Outcomes; tatsächliche unabhängige Grant-/Sessionrevoke und
   Deaktivierung blockieren neue Packets. Frühere Packets bleiben erhalten.
8. Wirkliche Alembicupgradefolge auf leerem und befülltem Roothead; zweimal
   Upgrade/Downgrade→frisches create_all im selben Prozess. Nonempty accepted
   Selection/Jobbelege sperren verlustreichen Downgrade. Alte komplette
   Read-/Selectionfamilienabwesenheit gültig, jede Teilfamilie beschädigt.
9. Raw-SQLite und PG-Recoveryvalidation: fehlendes Mitglied trotz falscher
   Count-/Digestangabe, orphan Read, doppelte Keys/Selectionjobs, fremder
   Membersource, falscher Outcome/Progress, Guardverlust. Originale nicht aus
   heutiger Notification nachbauen. Tatsächlicher Subprozessimportblocker
   verweigert Auth/Settings/Dependencies/App/Storage.
10. Tatsächliches Fullcontainerbackup/-restore mit Reads, accepted/unbound/
    expired Selections und teilweisem Job. Vor beschädigtem Original kein
    Session-/Claim-/Epoch-DML; Fehler später rollt kompletten Sicherheitsabschluss
    zurück. Alte Tokens/Claims anschließend unwirksam, persönliche Readfakten
    und Commandoriginale erhalten. Tenantprivacy/Reset/ordinary Deleteparität.
11. Große native Capture-/Packetmessung mit tatsächlichen Peak-RAM-/DB-/WAL-/
    Laufzeit-/SQLplanwerten. Bounded Worker ist kein Beleg für O(1)-Capture.
    Hardtimeouts sind Abbruch-/Rollbackbudgets, keine abgeschnittene Erfolgsauswahl.

PG nur dedicated `127.0.0.1:58112/immo_ci`, eigene UUID-Schemas, kein public/
Privatbestand, kein Servicechange. Kein Skip als native Abnahme. Jeder Gate
bekommt FrozenHEAD, genaue NodeIDs, Budget, individuelle Counts, reale Closure.
In diesem Vorcodeauftrag wurde kein solcher Gate gestartet.

## 10. Kleinste tragfähige Reihenfolge und Übergabe an UI

1. **A0 – Rootkomposition:** getypte Authority-/Sessioncommitbarriere,
   schmale RBAC-Regeln und SQLAuth/same-DB-Featurevoraussetzung festlegen.
   Migration-ID explizit koordinieren. Kein generischer Joboperatorlockern.
2. **A1 – eigene Quellen:** reine DTOs, ein gemeinsamer SQL-Eligibilitybuilder,
   bounded Livepage + vollständige Counts und transaction-only Einzel-Read;
   Readmodell/Validator. Root registriert Schema/Routes/References/Restore.
3. **A2 – native kleine Abnahme:** Mehrbenutzer-/selected-/readonly-/Scope/
   Timestamp-/Commit-Races, Migration/Restore, dann UI Live-Inbox/Badge/Read
   aktivieren. Mark-all false und snapshot_token null bleiben ehrlich.
4. **B1 – exakte Auswahl:** vollständiger SQL-Statementcapture, native Seal,
   serverseitiger Hashstream und explizite Vorbereitung/Preview; eigene
   Familymigration nur Rootkoordiniert. Retention-/Cleanup und großes
   Capturebudget beweisen, bevor Selectionfeature veröffentlicht wird.
5. **C1 – vorhandenen Jobkern komponieren:** persönliche Semantikversion4,
   Familyadapter und genaue Mitgliedsdiscovery; getypter Restorevalidator/
   Privacy-/Retentionpfad. Native Crash/Retry/Replay/Scopegates und große
   Mark-all-Packets. Dann UI Mark-all via tatsächlichem 202-Jobvertrag
   aktivieren, niemals die alte 10-PATCH-Schleife.

Root besitzt sämtliche Sharedcore-, Auth-/Schema-/Migration-/Registry-/
Recovery-/Referencecatalog-/Releaseentscheidungen. Die Domainownership für
spätere eigene Quellen wird erst gesondert zugewiesen. Dieser Plan
implementiert keinen dieser Pfade und beansprucht keine native Abnahme.
Die bestehende UIassistenz entwickelt weiter nur inaktive Hooks/Unterkomponenten;
ihr bisheriger synchroner Snapshot/Mark-all-Entwurf ist noch kein Backendvertrag.
