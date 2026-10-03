# M2: dedizierte PG-Fixture und offene Identitäts-CHECK-Prüfung

## Freigabe und Quellenstand

Vorcodeplan im vorhandenen eigenen Checkout, nach `3a6ae13`. Root hat das
vorherige Paket als `608890c/d543aad/72c0756` übernommen und meldet neun tatsächliche
HTTPfälle PASS. Hier werden diese Fälle nicht wiederholt. Kein Runtimeimport,
Test-, SQLite-/PG-, App-, Browser- oder Buildprozess wird gestartet. Root-Dateien,
Runtime/Recovery/Registry/CI und die inaktive M2-Platzierung bleiben unverändert.

## PG-Fixture: konkrete Änderung vor Code

Die bisherige Admin-Engine-/CREATE-SCHEMA-Sequenz liegt vor try/finally und
akzeptiert beliebige PostgreSQLziele. Sie bekommt ein eigenes Supportmodul,
das ausschließlich synthetische M2-Fixtures bedient, keine globale PG-Konfiguration.

Vor jedem möglichen Connect wird die URL erneut geprüft: Standard PostgreSQL
oder psycopg2, Host localhost/127.0.0.1, expliziter Port 58112 (Root) oder 5432
(CI), Datenbank und Benutzer exakt immo_ci. Keine Queryoptionen, kein Unixsocket,
Multi-host, alternativer Treiber oder fehlender Port. Parserfehler ergeben eine
feste Meldung ohne URL/Passwort. Danach entsteht eine neue kanonische URL mit
explizitem Loopbackhost und ausschließlich der übernommenen Passwortkomponente.
Libpq bekommt zusätzlich explizites hostaddr, Datenbank, Rolle und Port; fremde
options/hostaddr/service-URLparameter gelangen nicht zum Treiber.

Admin erhält nur pg_catalog als search_path. Die Fachengine erhält ausschließlich
das erzeugte notification_inbox_m2_<UUIDhex>-Schema. Jede tatsächliche neue
Connection prüft tatsächliche Datenbank, Benutzer, Adresse, Port und Schema vor
Fach-DDL. Connection-, QueuePool-, SQL- und Lockbudgets sind endlich. Ein
kooperativer 30-s-Node-Deadline begrenzt Connection-/Statementphasen; ein separater
8-s-Cleanup-Deadline bleibt auch nach Nodeablauf verfügbar. Der Root-Hardtimeout
bleibt nötig für CPUcode/DBAPIfehler, die sich nicht kooperativ begrenzen lassen.

Sämtliche Enginekonstruktion, Schemaanlage, Metadatensetup und yield liegen in
try/finally. CREATE und Ermittlung des eigenen Namespace-OID geschehen in
derselben tatsächlichen Transaktion. Cleanup schließt/disposed alle vorhandenen
Engines auch bei Setup-/Enginefehler, prüft native Poolcheckouts und benutzt für
DROP eine eigene bounded Adminengine. DROP erfolgt nur bei tatsächlich zuvor
erfasstem identischem eigenen Namespace-OID; fremde/ersetzte Schemas werden
nicht gelöscht. Unklare Cleanupzustände scheitern mit festem Code.

Vorbereitete isolierte Guardtests prüfen URLablehnungen vor create_engine sowie
Timeout- und Schemanamengrenzen. Sie schaffen keine DBAPIconnection. Die bisherigen
echten Operationsfälle benutzen den gehärteten Support. Kein Test wird jetzt
importiert oder ausgeführt.

## Tatsächlicher CHECK-Gap: Vorcodereview

`notification_inbox_validation._schema` liest PRAGMA table_info/foreign_key_list
bzw. SQLAlchemy columns/PK/FK. Kein Pfad liest SQLite Tabellen-DDL oder pg_constraint
für den Identitäts-CHECK. Danach endet er mit true. Die Datenprüfung iteriert
persönliche Zeilen; ein leerer Bestand oder vorhandene gültige Paare liefert true.
Daraus folgt durch Quellenkontrollfluss: identische geprüfte NativeShape ohne CHECK
und Shape mit gleichnamigem CHECK(1) werden aktuell akzeptiert. Das ist noch kein
ausgeführter Gegenbeleg. Eigene vorbereitete Rawfälle zeigen genau diese Bilder.

Ein allgemeiner SQL-Semantikparser wäre hier ein neues großes Produkt. Name,
Whitespace-/Regexnormalisierung oder einzelne Schlüsselwörter beweisen den
Schutz nicht: CHECK(true), OR true, Stringliteral statt Column, Not-Validated-PG-
Constraint und eine anders gebundene length-Funktion können dieselbe Oberflächen-
form zeigen. Bewusste Probe-INSERTs sind in einem echten lesenden Validator verboten.

Deshalb wird in diesem Nachtrag **keine Validator-Parserfähigkeit behauptet oder
aktiviert**. Die konkrete nachfolgende Sourcekomposition ist unten festgelegt.
Vorbereitet werden strikte erwartete Refusaltests mit ausdrücklich markiertem
bekannten Gap, nicht als grüne Abnahme. Die bekannte valide Rawfixture bekommt
ihren realen benannten CHECK; die bereits grünen HTTPfixtures haben ihn über
die tatsächlichen ORM-Tabellen ohnehin.

## Implementierbarer enger Schema-/Katalogvertrag für die nächste Phase

Die nächste Umsetzung sollte ausschließlich den veröffentlichten M2-/ORM-
Constraint als enges kanonisches Format akzeptieren, keine beliebige semantische
Äquivalenz versprechen. Vollständige Familieabsenz bleibt false. Existierende
Familie muss einen vollständig bewiesenen Schutz für **beide** nichtleeren IDs
enthalten. Ein zusätzliches CHECK(true) darf einen vorhandenen gültigen Schutz
nicht aufheben; ein gleichnamiger schwacher Schutz allein muss verweigern.

SQLite: tatsächliche main.sqlite_schema/sqlite_master-Tabellen-DDL anhand des
festen Tabellennamens auf derselben Connection lesen. Ein begrenzter SQLtokenizer
muss Kommentare, quoted identifiers und Stringliterale unterscheiden sowie
balancierte Table-/Constraintklammern auswerten. Nur der echte benannte Table-
CHECK und eine begrenzte AST aus AND, length(Column) und > integer-zero sind
akzeptiert. Columns müssen genau actor_id/notification_id sein, nicht Literale.
Nicht erkannte Syntax scheitert mit festem CHECK-Code. DDLbyte-/Token-/Tiefe-
Grenzen und deadline vor/nach Parse verhindern ungebundenes Parserarbeit.
Zusätzlich ignore_check_constraints muss auf der tatsächlich prüfenden Connection
aus sein. Eine connectionlokale Userfunktion length darf die Builtinsemantik
nicht ersetzen; diese Auflösung ist separat anhand nativer function_list-/
Connectiongarantien zu beweisen, sonst Refusal. Tabellen-DDL allein beweist weder
eine deaktivierte CHECKausführung noch eine überschattete Funktion.

PostgreSQL: Schema-/Relation-OID zuerst aus actual current_schema/pg_namespace/
pg_class festlegen. pg_constraint exakt an dieses conrelid binden, contype='c',
korrekter conname, convalidated=true und tatsächliche Attrnummern für beide IDs.
convalidated beweist bestehende Zeilenprüfung, keine Expressionsemantik. Für
PostgreSQLversionen mit conenforced muss die Enforcementeigenschaft ebenfalls
positiv sein. Native Serverversion/-katalogvariante gehört in den Vertrag.

Die Expression braucht einen tatsächlichen nativen Strukturbeleg: bevorzugt
eine eng begrenzte Erkennung der gespeicherten conbin pg_node_tree für genau
BOOL_AND + zwei int4-GT-nullfreie-0-Konstanten + pg_catalog.length(text) auf den
richtigen VAR-Attnummern mit ausschließlich erlaubten varchar→text Relabels.
Funktions-/Operator-/Typ-OIDs aus pg_catalog lesen und anhand dieser konkreten
OIDs prüfen; nicht aus einem unqualifizierten pg_get_expr-Namen ableiten.
VARrelation/level, Coercions, Constant-Typ/Nullflag und Boolop müssen passen.
pg_node_tree ist ein versionsgebundenes internes Format; positive echte native
Snapshots der tatsächlich unterstützten Root-/CI-Server sind Voraussetzung für
dieses enge Format. Unbekannte Nodes/Felder oder Versionen dürfen nicht als
geprüft durchgehen. Ein unabhängiger Native-Gegenbeleg muss die im Katalog noch
NOT VALID vorhandene Checkform verweigern, auch bei leerem Bestand.

Falls dieser begrenzte Native-Treevertrag in den unterstützten Versionen nicht
wartbar nachweisbar ist, bleibt die Grenze offen bis ein überprüfter primärer
SQLparser/Nativekatalogadapter gewählt wird. Ein Regex auf pg_get_constraintdef
ist kein Ersatz. Validator bleibt SELECT/PRAGMA-only, ohne DML oder Sessionrepair.

## Nächste Abnahme und offene Grenzen

Zuerst echte SQLite-/PG-Katalogbeispiele des unveränderten M2/ORM-CHECK erzeugen,
danach Parser-/OID-Vertrag vor Code separat freigeben. Pure Parser-/Rawtests:
fehlend, true, OR true, nur eine ID, Literalfunktionargument, Kommentare/Quotes,
harmloser Whitespace/Klammern, Budgetablauf und verbotene Runtimeimports.
Native PG separat: echte Constraint-OIDs, validated/unvalidated, falsch gebundene
Relation/Funktion/Operator, zulässige casts, false-Enforcement falls unterstützt.
Native DML gehört ausschließlich in synthetische Migrationstestbilder, nie in
die Produktvalidierung. Aktuelle PostgreSQL-/Fullcontainer-/Head-/Coldstart-
Abnahme und positive CommitAuthority bleiben weiterhin offen/getrennt.
