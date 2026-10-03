# M2-Nachtrag: saubere Quellen, keine neue native Abnahme

Eigener Checkout `work/encrypted-runtime-factory`, Branch
`assist/notification-inbox-readonly`. Vorplan `a913e2f`, PG-Fixture/Guardquellen
`fcfbd34`, CHECK-Gap-/Rawfixturequellen `38d37ab`. Root bleibt unverändert.

Tatsächlich geprüft: Quellendiffs und `git diff --cached --check` ohne Befund.
Kein Python-/Ruff-/Mypy-/Import-/Test-/HTTP-/SQLite-/PG-/App-/Browser-/Buildlauf.
Die von Root dokumentierten 9 HTTP / 8 Recovery / 6 SQLite-Operations-PASS auf
`b8e793c` werden hier weder wiederholt noch als Abnahme dieser neuen Fixture
ausgegeben. PostgreSQL und die neuen Guard-/Gegenbelegfälle bleiben ungestartet.

## PG-Fixture: exakter Einsatz

Die bestehenden fünf `[postgresql]`-NodeIDs in
`backend/tests/test_notification_inbox_migration_proposal.py` bleiben unverändert:

- `test_native_proposal_exact_shape_and_empty_down_up[postgresql]`
- `test_native_proposal_rejects_existing_family_without_repair[postgresql]`
- `test_native_personal_evidence_is_not_global_read_backfill_and_blocks_downgrade[postgresql]`
- `test_native_personal_pair_uniqueness_and_both_parent_cascades[postgresql]`
- `test_native_required_read_fields_and_identity_guard[postgresql]`

Der Fixturekontext verwendet ausschließlich
`backend.tests.notification_inbox_pg_proposal_support.postgres_proposal_database`.
Keine öffentliche Produkt- oder globale Datenbank-API wurde ergänzt. Auswahl
für späteren Rootlauf: genau diese Datei mit `-k postgresql` auf expliziter
`TEST_SERVER_DATABASE_URL`; kein Fallback/Skip. Die sechs SQLitefälle bleiben
separat. M2 bleibt weiterhin unter proposals und wird nicht aktiviert.

Zielvertrag: `postgresql`/`postgresql+psycopg2`, localhost oder 127.0.0.1,
**expliziter** Port 58112 oder 5432, Benutzer und DB jeweils immo_ci. Sämtliche
URLqueryoptionen werden verweigert, einschließlich options/host/hostaddr/service.
URLparserfehler sind valuefrei. Kanonische neue URL und DBAPIparameter setzen
host und hostaddr auf 127.0.0.1 sowie Rolle, Datenbank und Port explizit. Nur eine
explizite Passwortkomponente bleibt für Authentifizierung erhalten; keine URL-
oder Schlüsselwerte werden protokolliert. Kein fremdes options wird übernommen.

Vor jedem DBAPIconnect wird der Zielvertrag erneut geprüft; anschließend prüft
dieselbe tatsächliche neue Connection DB/User/Adresse/Port/Schema vor Fach-DDL.
Adminsearchpath ist pg_catalog, Fachsearchpath ausschließlich eine eigene UUID-
Namespace. Namespace-OID und owner werden in derselben CREATE-Transaktion erfasst;
Cleanup verweigert ein unter demselben Namen ersetztes Namespace.

Budgets: 30 s kooperativer Node, QueuePool maximal 2 s, Connect maximal 3 s,
SQL maximal 5 s, Lock maximal 1,5 s, Idle-in-Transaction 5 s. Vor jedem SQL werden
SQL-/Locktimeouts anhand des dann verbleibenden Budgets reduziert. Das benutzt
einen separaten geschlossenen DBAPIsettingscursor und berührt einen etwaigen
named Streamingcursor des tatsächlichen Validators nicht. Connectgranularität
von libpq ist eine Sekunde; Deadlinechecks nach Connect/SQL erkennen Überlauf.
Diese Grenzen ersetzen keinen äußeren Root-Prozess-Hardtimeout für CPU oder
unkooperatives DBAPI-/Betriebssystem-I/O. Für Cleanup entsteht ein separater
8-s-Deadline; die konstruktive Gesamtgrenze ist daher Node+Cleanup mit diesen
nativen Rundungs-/I/Ogrenzen, kein bereits gemessener harter 38-s-Beleg.

Alle Enginekonstruktion/Setup/yield liegen im Cleanupkontext. Jeder tatsächlich
erzeugte native DBAPIhandle wird vor Dialektinitialisierung als eigenes Objekt
aufgezeichnet. Cleanup schließt auch checked-out Handles, die engine.dispose
allein nicht schließen würde. Checkedout-Zustände bleiben ein fester Fehler,
kein stiller Erfolg. Ein eigenes neues bounded pg_catalog-Admin führt DROP nur
für erfasste gleiche Namespaceidentität aus; Setup-/Fachenginefehler führen über
denselben finally-Pfad. Fehler sind feste Cleanupcodes. Diese Ausfallpfade sind
noch nicht nativ nachgewiesen; keine zusätzliche Fixture-/API-Erweiterung.

Vorbereitet sind 17 pure Guardfälle in
`backend/tests/test_notification_inbox_pg_proposal_guards.py`: zwei gültige
Loopbackziele, 14 ungültige Ziele/Queryoptionen vor jeglicher Enginekonstruktion
und ein Schema-/Deadlinefall. Zahl aus Quellparametern, keine echte Collection
oder Erfolgsmeldung. Diese Datei importiert keine Auth/App/ORMmodelle.

## CHECK: tatsächlicher Gap bleibt sichtbar und ungelöst

Keine Validatorquelle wurde geändert. `notification_inbox_validation._schema`
liest weiterhin keinen nativen CHECK-Katalog. Eigene vorbereitete Rawbilder
mit vollständiger geprüfter Shape und gültigen persönlichen Zeilen haben
fehlenden CHECK, CHECK(1), OR 1, nur actor_id oder Stringliteralargumente. Aus dem
aktuellen Kontrollfluss folgt eine Annahme bis true; **kein Bild wurde ausgeführt**.

Die fünf Fälle in `test_notification_inbox_identity_check_gap.py` verlangen
echte Refusal, sind aber als **strict xfail für den bekannten fehlenden Beleg**
markiert. Ein zukünftiger xfail ist keine positive Sicherheitsabnahme. Nach
tatsächlicher Validatorimplementierung muss die Markierung entfernt werden;
XPASS ist absichtlich ein Fehler. Diese Gegenbelegdatei gehört nicht in den
jetzt geplanten fünf-PG-Operationslauf.

Die bestehende valide Rawfixture in `test_notification_inbox_validation.py`
enthält nun den tatsächlichen benannten CHECK für beide IDs. Bereits grüne
HTTP-/ORM- und eigene Recoveryfixtures haben diesen Guard bereits; keine
HTTP-/Auth-/Modeländerung und keine Originalzeit-/Bestandsmigration.

Der präzise Sourceplan steht in
`NOTIFICATION_INBOX_M2_FIXTURE_CHECK_REVIEW_PLAN_20261004.md`: begrenzte tatsächliche
SQLite-DDL-AST plus aktive CHECK-/Builtinfunktionsemantik; PG Relation-/Attr-OIDs,
convalidated (und versionsabhängig conenforced) plus enger nativer conbin/OID-
Strukturbeleg. Keine Regex-/Namensabnahme, kein DML im echten Validator. Dazu
braucht es zuerst echte positive native Katalogbeispiele der unterstützten
Root-/CI-Server und einen versionsgebundenen Formatvertrag. Hier wurde kein
allgemeiner SQLparser gebaut oder eine solche Fähigkeit vorgespiegelt.

Gemeinsame tatsächliche L2/M2-Registry-/Head-/Startup-/Fullcontainer-Komposition,
vollständiger nativer CHECKbeleg und positive CommitAuthority bleiben getrennt
offen. Keine SharedRuntime/Recovery/Registry/CI-/Migrationaktivierung in diesem
Nachtrag, kein A–L-Gesamtclaim.

## Tatsächlicher erster Root-PG-Lauf und Korrektur vor Code

Auf0570d9f: fünf ausgewählte PostgreSQL-Operationsfälle scheitern beim
Fixture-Connect, 5ERROR in3,08s/hard90/Exit1; sechsSQLitefälle abgewählt.
Kein CREATE SCHEMA oder Migrationsaufruf erreicht, keine native Abnahme.
Die tatsächliche Adresse wird als inet nach text mit Netzmaske ausgegeben.
Ein separat begrenzter echter Testziel-SELECT beweist zugleich
`inet_server_addr()::text='127.0.0.1/32'` und
`host(inet_server_addr())='127.0.0.1'`. Datenbank/Rolle/Port/Schema sind
immo_ci/immo_ci/58112/pg_catalog.

Root korrigiert ausschließlich die Adresseprojektion zur expliziten nativen
`pg_catalog.host(pg_catalog.inet_server_addr())`. Ziel, Loopbackvertrag,
Timeouts und Cleanup werden nicht gelockert. Anschließend werden genau die
fünf bislang nicht ausgeführten Operationsfälle erneut nativ geprüft.

Korrigierter tatsächlicher Gate auf3c96be9: 5PASS in3,40s/hard90/Exit0,
sechsSQLitefälle ausdrücklich abgewählt. UUID-Schemas, eigene Handles und
Poolcheckouts erfolgreich aufgeräumt. Bericht
`artifacts/NOTIFICATION_INBOX_M2_PG_OPERATIONS_ADDRESS_CORRECTED_20261004.xml`.
Native Katalog-/OID-/conbin-Beobachtung im eigenen zusätzlichen Schema wurde
unverändert in `artifacts/NOTIFICATION_INBOX_M2_PG16_NATIVE_CHECK_20261004.json`
gesichert; sie ist eine Parsergrundlage, noch kein tatsächlicher Validator.

EigenerPG16.15-Prozess13000, nur127.0.0.1:58112, anschließend normal per
pg_ctl fast/wait beendet; keinePiddatei und keinListener58112 bleiben.
Kein tatsächlicher K2→L2→M2-Upgrade/Produktionsstart oder Fullrestoreclaim.
