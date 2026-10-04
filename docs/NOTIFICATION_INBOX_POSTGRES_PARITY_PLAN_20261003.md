# Persönliche Live-Inbox: PostgreSQL-Quellenplan vor Code

03.10.2026; ausschließlich eigener Checkout
`work/dashboard-notification-timestamps`. Sourcealgorithmus bleibt der eigene
A1-/Validatorstand bis `594cb78`/`7b7b0ae`. Root meldet separat 12 Pure-PASS
auf `5dcd35a`, fünf SQLite-PASS auf `ed70ae8` und den nach reinem CursorResult-
Fixturefix `2e58c12` gezielt bestandenen sechsten Fall. Keine vollständige
erneute Sechserabnahme, keine eigene PG-/HTTP-/positive Writeabnahme.

## Tatsächlich gelesener Defaultwriter

- `backend/repositories/sql_store.py:699`: create_notification delegiert.
- `backend/repositories/communication_repo.py:125`: generisches create,
  anschließend tatsächlicher Sessioncommit.
- `backend/repositories/base.py:225,243`: ORM aus NotificationCreate-Daten;
  tatsächliches flush/refresh. `_to_pydantic` übernimmt ORM-Spaltenwerte.
- `backend/models.py:884`: NotificationCreate hat kein created_at/updated_at.
  Die UTC-defaultfactory des Readmodells Notification ersetzt keinen bereits
  durch das ORM gelieferten Spaltenwert.
- `backend/db/orm_models.py:640`: created_at ist plain DateTime mit func.now;
  auch updated_at benutzt diesen Default. Der bestehende allgemeine
  DateTimevertrag wird in `base.py:105` ausdrücklich als UTC ohne Zone benannt.
- `notification_inbox._order` behandelt PG als typisierten Zeitwert; keine
  nachträgliche Zeitzonenumrechnung kaschiert den gespeicherten Wert.

Das ist ein konkreter möglicher Default-/Sessionzonenfehlerpfad, noch kein
gemessener PG-Befund. Es wird kein Timestampproduktcode geändert. Zwei echte
vorbereitete Writertests müssen erzeugten, gespeicherten und von der Inbox
gelieferten naiveUTC-Zeitwert mit einem eigenen tatsächlichen UTCbefore/after-
Fenster vergleichen. Kein xfail und kein Session-/Serverzonenfix im Writer.

## Neue eigene Testquelle und Isolation

Nur `backend/tests/test_notification_inbox_postgres.py` wird ergänzt.
Keine vorhandene Fixture, Registrierung, Migration, Auth, Router oder Recovery
wird bearbeitet. Kein Runtime-/Import-/DB-/PG-/CLI-/Browserstart im Auftrag.

Fixture verlangt TEST_SERVER_DATABASE_URL ausdrücklich, fehlt es: FAIL,
niemals Skip/SQLitefallback. Vor jedem connect URL auf tatsächlichen dedizierten
Targetvertrag prüfen: PostgreSQL, immo_ci@127.0.0.1:58112/immo_ci. Zusätzliche
URL-Queryoverrides außer options werden abgewiesen; vorgegebene Connectionoptions
werden überschrieben. Adminsearchpath nur pg_catalog,
Fachsearchpath nur zufälliges `inbox_pg_<uuidhex>` ohne public.

Ein unabhängiger Adminengine erstellt ausschließlich dieses UUID-Schema.
Zwei getrennte Fachengines mit eigener Poolgröße und harten Connect-/SQL-/
Locktimeouts belegen getrennte tatsächliche PG-backend_pids im selben Schema.
Alle tatsächlichen Tabellen werden ausschließlich hier per explizitem
Base.metadata.create_all aufgebaut: ehrlicher Modelltest, keine Migrationabnahme.
Nötiger DocumentVersion-Metadatenimport bleibt erhalten; keine Sharedregistrierung.
Reale SQLUserStore-Factory, aktiver Owner und zwei echte selectedReadonlyActors,
zwei Portfolios/Properties/Units. Fresh Actor via tatsächlichem SQLUserStore,
keine Authgetter-/Actorlambda-/CommitAuthoritymocks.

LegacyNULL-Fall: Notificationtable zuerst in eigene MetaData kopieren,
created_at nur in der Kopie nullable machen und im eigenen Schema vor den
Readpair-FKs erzeugen. Anschließendes create_all überspringt die vorhandene
Tabelle. Die globale Originalmetadatenquelle wird niemals mutiert.

finally schließt caller Session, prüft beide zurückgegebenen Pools und entsorgt
Fachengines; äußeres finally entfernt exakt das generierte UUID-Schema und
entsorgt Adminengine auch bei Setup-/Testfehlern. Kein public, keine fremden
Schemas, kein Service-/Postmasterstart oder PIDeingriff.

## Geplante fünf tatsächliche expanded Fälle

1. **10002** berechtigte aktive Notifications, alte globale Reads weiterhin
   aktiv, dazu begründet unsichtbare Scope-/Dispatch-/Unknown-/Broken-/Archived-
   Zeilen. Echte Unit→Property→Portfolio-Eltern und explizite Resourcegrants;
   zugewiesen unlinked erlaubt, zugewiesen halbfehlend unsichtbar. Historische
   persönliche Paare für zwei Actors getrennt. SQL-counts oberhalb jedes
   Seitenbudgets, komplette Keysetdurchläufe mit limit100/limit+1 über all,
   unread/read und exakten Typ-/Severityfilter; Filtercounts und unread_count
   sind vom persönlichen Statusfilter unabhängig. Read-only SQLtrace,
   tatsächliche bounded Projektionslimits und verbotenes Stockrepository.
2. Vorhandenen Cursor gegen echten zweiten Actor und veränderte Query ablehnen;
   Grantänderung via reale SQLUserStore.update mit tatsächlichem Owner. Alter
   Scope403, neu gelesener Scope mit altem Cursor422. Owner-origin in tatsächlich
   unabhängiger SQLconnection auf den existierenden legacy_all-Wert ändern;
   effektiver Scope bleibt gleich, alter Cursor muss trotzdem422 sein.
3. Echter PG-func.now-Default im einen nativen Bulkstatement liefert Gleichstand;
   zusätzliche tatsächliche typisierte Nullfraktion/Mikrosekunde und kopierte
   LegacyNULL-Zeilen. Byteweiser Unicode-Tiebreak und jede ID genau einmal.
4.–5. Echte SQLAlchemyStore.create_notification mit NotificationCreate ohne
   Callerzeit unter Europe/Berlin bzw. America/New_York. Eigene UTCclocks aus
   unabhängigem Fachengine, before **vor** Beginn der Writertransaktion (now
   kann deren Beginn abbilden), after **nach** dessen tatsächlichem Commit.
   Sessionzone tatsächlich setzen/messen, gespeicherten und zurückgegebenen
   Wert sowie Inboxprojektion streng auf naiveUTC/Window prüfen. Sessionzone
   danach explizit zurücksetzen; alle Quellen bleiben unverändert.

Keine positiven stage_read-, HTTP-, Sid-/Commitraces oder Restoreprüfung als
Nebenprodukt behaupten. Historische Readpaarfixtures sind kein Writebeleg.

## Noch nicht genehmigte Gatevorschläge

Nach FrozenSource und Rootfreigabe seriell: zuerst Nodes2/3 hart120s; dann
großer Node1 hart300s einschließlich 10002-Bulkseed/aller Seiten/Cleanup;
anschließend beide strikten Writernodes hart90s. Innerer SQLtimeout20s und
Connecttimeout5s, kein paralleler Root-/UI-/PG-Lauf. Die Zeitbudgets sind
vorläufige Vorschläge, keine Laufgenehmigung oder behauptete Messwerte.
Wenn ein Zonenfall den UTC-Vertrag verletzt, echten FAIL melden und Root eine
eng begrenzte Produktentscheidung vorlegen; kein Timestamp-Massenfix hier.
