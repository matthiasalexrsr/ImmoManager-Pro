# Persönliche Inbox A1: Quellenübergabe ohne Runtimeabnahme

03.10.2026; Checkout `work/dashboard-notification-timestamps`, Branch
`assist/dashboard-notification-timestamps`. Umsetzung ausschließlich eigener
Featurequellen; Root/Main/Preview und fremde Quellen nicht bearbeitet.

## Saubere Commitfolge

Grundplan `2d1002c` wurde von Root gelesen und Phase A1 daraus autorisiert.
Die danach separat entstandenen Commits in dieser Reihenfolge übernehmen:

1. `688ccf9`: präziser Vorcodevertrag, einschließlich zwingendem Rootbeleg.
2. `4893b95`: reine DTOs, explizites Readpairmodell und reine Validierung.
3. `d14175f`: SQL-Livequery und ausschließlich vorbereiteter Staged-Write.
4. `fa6412a`: eigene vorbereitete Pure-/Raw-/SQLite-Testquellen.
5. `c5bad56`: read-only Defaults/Releaseflag, halbfehlende Scoped-Referenzen
   abweisen und entsprechende vorbereitete Regressionen.

Keine Migration, zentrale Registrierung, Router-, Auth-, Middleware-, Job-,
Recovery- oder UIänderung enthalten. `l2` bleibt TEHA. Selection/Mark-all/Jobs
wurden nicht implementiert und sind kein Bestandteil dieser Quellenabnahme.

## Tatsächliche Featureinterfaces

```python
list_inbox(store, query: InboxQuery | None = None,
           *, read_actions_enabled: bool = False) -> InboxPage
stage_read(db: Session, notification_id: str,
           *, authority: object) -> NotificationReadResult
validate_notification_inbox_schema(connection, *, deadline=None) -> bool
validate_notification_inbox_database(connection, *, deadline=None) -> bool
```

Readquery: unread/read/all; exakte optionale notification_type/severity,
after, limit 1–100/default10. Requestextras, insbesondere Actor/Scope/
Releaseflag/Snapshottoken, sind verboten. Die öffentliche Page hat volle
SQL-counts, bounded Items, has_more/next_cursor, consistency=live und
snapshot_token=null. unread_count berücksichtigt Typ/Severity, nicht den
Status-/Cursorfilter. Globale Notifications mit read/unread gelten als aktiv;
archived wird ausgeschlossen. Persönlicher Readstatus stammt ausschließlich
aus `notification_read_states` für den frisch ermittelten tatsächlichen Actor.

Standardmäßig sind Item-actions.mark_read=false und mark_all_read=false.
Der interne Keywordparameter ist ausschließlich UI-Releasemetadatum. Root
darf ihn erst nach tatsächlicher HTTPwrite-Abnahme aktivieren; auch true
autorisiert keinen Aufruf von stage_read. Keine Root-HTTProute enthalten.

Der Readpfad verlangt tatsächliche SQLUserStore-/Business-Verbindungen zur
selben persistenten SQLitehauptdatei bzw. PG-Server-/Database-/Schemasignatur.
Frische User/Access/Grantwerte vor und nach dem Fachread müssen dem realen
current_scope entsprechen. Memory oder getrennte Quellen ergeben ehrlich503.
Root muss den äußeren tatsächlichen HTTPcredential-/Publicationcheck weiterhin
komponieren; ContextVar/Principaldaten allein belegen keine HTTPcredential.

Counts und Projektion verwenden dieselbe SQL-Eligibility vor LIMIT: bestehender
Scopecompiler, aktive Statuswerte, Dispatchrolle und optionale exakte Filter.
Echte explizit zugewiesene unlinked Zeilen können sichtbar sein; halbfehlende
entity_type/entity_id-Paare bleiben für eingeschränkte Scopes unsichtbar.
Cursor benutzt den vorhandenen HMAC-Kern und bindet Actor, Scope, Access/origin,
Grants, Query/Limit/Sort/Version. Native SQLite-Nullfraktion wird verlustfrei
kanonisiert; PG bleibt DateTime; NULLs folgen zuletzt und IDs sind byteweise.
Livepaging behauptet keine stabile Auswahl unter Inserts oder Reads.

## Zwingende Rootkomposition vor tatsächlichem Einzelread

`backend.services.notification_inbox_commit_authority` ist ein noch fehlendes
Sharedmodul. Es muss die konkrete `NotificationReadCommitAuthority` und
`require_notification_read_authority(db, notification_id, proof)` bereitstellen.
Letzteres liefert genau den eigenen `InboxPrincipal`, nachdem es tatsächliche
native Sid-/Account-/Scopeparentfences für dieselbe Session/Transaktion/Target
belegt hat. Ausgabe nur durch Root, keine frei konstruierbare Daten-Capability.
Der Beleg muss während tatsächlichem Commit/Rollback gültig bleiben; finale
Expiry-/Revocation-/Authorityprüfung ist Caller-/Rootownership.

stage_read verlangt aktive caller-owned Session/Transaktion, prüft nominell
exakt die Rootklasse und ruft den Rootverifier vor und nach eigenem DML auf.
Fehlendes Rootmodul ergibt503; fake bool/Lambda/Principaldaten werden nicht
akzeptiert. Reale aktuelle Accountbindung und Eligibility werden zusätzlich
geprüft. Insert-once benutzt DB-UTC-Zeit und ON CONFLICT DO NOTHING auf dem
Actor/Notification-Paar; keine Notification-/Globalstatusänderung. Der Helper
eröffnet, beendet oder committed keine fremde Transaktion. Caller muss Fehler
nach DML vollständig zurückrollen. Noch kein positiver Schreibnachweis.

Root muss `notification_read_states` in die explizite interne Scopeklassifikation
einordnen: die bestehenden Session-Core-Interceptor würden sonst den Pairtable
als generische Ressource behandeln. INTERNAL allein ersetzt den oben zwingenden
Actor-/Target-/Commitbeleg nicht. Readcounts verwenden unabhängige Connections
mit expliziter Eligibility und verlassen sich nicht auf diesen Interceptor.

## Modell-, Migration- und Recoveryanschlüsse

`backend/db/notification_inbox_models.py` definiert ausschließlich
NotificationReadStateORM/NOTIFICATION_READ_MODELS. Paar-PK(actor_id,
notification_id), NOTNULL naiveUTC read_at, beide tatsächlichen Parent-FKs
mit CASCADE. Keine automatische globale Registrierung/DDL.

Root koordiniert Modellimport in session/migrations.env, eine echte reservierte
Revision/Singlehead, frühe Runtime-/Partial-Schemaprüfung und INTERNAL wie oben.
Das hier reine Schemahelper verlangt Form/PK/FKs/Typen; Serviceabwesenheit ist
503. Der vollständige Databasehelper akzeptiert komplette Legacyabwesenheit
als False, weist Teil-/beschädigte Schemata, fehlende tatsächliche Parents und
ungültige Zeitformen ab und streamt Paarbestand in 64er Batches. Keine DDL/DML,
Auth/Store/Config/ORMimports; Caller besitzt konsistenten Snapshot/Deadline.

Root schließt den vollständigen reinen Validator in full_recovery,
recovery_validation und recovery_sessions vor Pathrewrite, Claimreset,
Sessioninvalidate und Restore-DML an. Persönliche Readmetadaten bleiben bei
Restore erhalten; CASCADE auf tatsächlich entfernte User/Notifications bleibt
bewusste Löschsemantik. Readpaare sind keine finanziellen Originalbelege und
erhalten keine pauschale finanzielle Retentionssperre. Root owns getypte Reset-,
Privacy- und Referenzkomposition. Kein eigener Factory-/Registry-/Recoveryedit.

## Tatsächlicher Prüfstand und nächste kleinste Gates

Nur Quellen/Diffs gelesen; `git diff --check` erfolgreich. Kein Pythonimport,
Pytest, DB-/Auth-/App-/Server-/Browserprozess und kein PG-Servicewechsel in
diesem Auftrag. Keine PASS-/Runtime-/Feature-/Releasebehauptung.

Vorbereitet: **12** expanded Pure-/Rawfälle in
`backend/tests/test_notification_inbox_validation.py`, einschließlich echtem
Subprozess-Importblocker. Nächster möglicher genehmigter Slot: diese Datei mit
`--noconftest`, ein Prozess, vorläufig hart30s einschließlich Kindtimeout15s.
Das ist ein Vorschlag, keine bestehende Laufgenehmigung.

Vorbereitet: **6** native SQLitefälle in
`backend/tests/test_notification_inbox.py`: persönliche SQL-counts/Mehrbenutzer,
gemeinsame Scope/Dispatch/Filtereligibility, Actor/Query/Grant-Cursorbindung,
native CURRENT_TIMESTAMP plus SA-Zerofraktion/Mikrosekunde/NULL, Memory/getrennte
Authquelle503 und Fakecapabilities ohne Read-DML. Tatsächliche SQLUserStore-
Fixtures; kein Authgetter-/Actoroverride. Historische Readpaarfixtures sind
keine positive Staged-Writeabnahme. Nächster möglicher separater Slot: diese
sechs Nodes, vorläufig hart120s, eigener fileSQLite-Store, kein PG parallel.

Offen: tatsächliche Runtimeimport-/SQLiteergebnisse, großer tatsächlicher
Bestand über137 Rows, echte PG-Parität/eigene UUIDSchemas, Migration/Restore,
positive insert-once-Replays und unabhängige Write-/Sid-/Account-/Parentraces
samt vollständigem Rollback nach Erst-DML. HTTPcredentials/Readonly-Ausnahme/
Releaseflagaktivierung benötigen die echte Rootkomposition. Kein Mockbeleg
darf diese Gates ersetzen; kein Skip gilt als Abnahme.
