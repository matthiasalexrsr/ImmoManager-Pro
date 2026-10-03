# Persönliche Inbox: vorbereitete PostgreSQL-Parität

03.10.2026; eigenes `work/dashboard-notification-timestamps`.
Saubere neue Commitfolge: `c0f56dc` Vorcodeplan → `10cf3db` Testquellen.
Keine Produkt-/Sharedcore-/DDL-Migration-/Registry-/Auth-/Recovery-/Router-
Änderung. Die ergänzte Quelle ist ausschließlich
`backend/tests/test_notification_inbox_postgres.py`; zwei eigene Plandokumente.

**Prüfgrenze:** Source gelesen und git diff --check erfolgreich. Hier kein
Pythonimport, Runtime-, Pytest-, App-, CLI-Bootstrap-, Browser-, DB- oder
PG-Serviceprozess gestartet. Kein PG-PASS, keine positive persönliche
Write-/HTTP-/Sid-/Migration-/Restoreabnahme. Roots frühere tatsächliche
12 Pure-PASS und 5+1 unterschiedliche SQLite-PASS sind eigene Rootnachweise,
keine Ergebnisse dieser neuen fünf expanded PG-Quellenfälle.

URL-Pflicht ausdrücklich fail-closed ohne Skip/Memory-/SQLitefallback;
dedizierter Target immo_ci@127.0.0.1:58112/immo_ci. Queryoverrides außer den
überschriebenen options abgewiesen; Admin nur pg_catalog, Fachconnections nur
eigenes zufälliges UUID-Schema. Reale SQLUserStore-Accounts: Owner und zwei
selectedReadonlyActors, native Unit/Property/Portfolioeltern, Dispatch-/Resource-
grants und historische persönliche Readpaare. Kein Authgetter-/Actoroverride.
Zwei Fachengines und tatsächliche PID-/Schemaassertions; eigene Poolprüfung,
Session-/Enginedispose und exakt begrenztes finally-DROPSCHEMA vorbereitet.
create_all ist ausdrücklich Modelltest, keine vorhandene Migration behauptet.
LegacyNULL verändert ausschließlich eigene MetaData-Kopie, nie Basequelle.

Großfall:10002 tatsächlich berechtigte aktive Rows, sechs vollständige Walks
all/unread/read mit und ohne Typ-/Severityfilter, limit100 und tatsächliche
Projection-LIMIT101-Trace. SQL-counts, individuelle zwei-Actorreads, versteckte
fremde/kaputte/rollenfremde Rows, explizites unlinkedGrant und unveränderte
globale Reads. Stockrepository verboten, GET-DML abgewiesen. Eigene erwartete
Fixturelisten bilden den Testoracle; Service darf keinen Bestand materialisieren.

Konkreter Writerbefund ist bisher **statisch**: SQLAlchemyStore delegiert über
CommunicationRepository und BaseRepository.create/flush/refresh an plain
NotificationORM.DateTime mit func.now. Kein Zeitfeld in NotificationCreate;
Readmodell-UTC-defaultfactory ersetzt den gespeicherten Wert nicht. Die zwei
Zonefälle pinnen die tatsächliche Writerconnection über den echten Repocommit,
setzen/messen Europe/Berlin bzw. America/New_York und vergleichen erzeugten,
gespeicherten und Inboxzeitwert mit unabhängigem DB-UTCbefore/after-Fenster.
before liegt vor Writer-BEGIN; after folgt dessen tatsächlichem Commit.
Explizite UTC-Zonenbereinigung derselben physischen Connection im finally.
Kein xfail, kein Timestampfix oder behaupteter PG-Serverzonenbefund.

## Exakte noch nicht freigegebene serielle Gateauswahl

Pfadpräfix für alle Nodes: `backend/tests/test_notification_inbox_postgres.py::`.

1. Hart120s, zwei Nodes:
   `test_postgres_actual_actor_grant_and_origin_cursor_bindings` und
   `test_postgres_native_ties_microseconds_and_legacy_null_keysets[legacy-null-schema]`.
2. Hart300s, ein Node:
   `test_postgres_10002_personal_counts_and_all_live_keysets`.
3. Hart90s, zwei Nodes:
   `test_postgres_create_notification_default_is_naive_utc_in_session_zone[Europe/Berlin]` und
   `test_postgres_create_notification_default_is_naive_utc_in_session_zone[America/New_York]`.

Nur nach Rootslot/Sourcefreeze und tatsächlicher URLfreigabe, ein Prozess,
keine parallelen Native-/PG-/Browsergates. Connecttimeout5s/Pooltimeout5s,
innerer SQLtimeout20s/Locktimeout5s. Vorläufige Budgets noch nicht gemessen.
Fixture-/Infrastrukturfehler ehrlich von Produkt-PASS/FAIL trennen; Cleanup
und Poolschluss tatsächlich nachweisen. Falls UTCwindow verletzt wird, echten
FAIL festhalten und einen schmalen Rootproduktfix abstimmen; nicht andere
Timestampfamilien ungeprüft ändern oder als grün markieren.
