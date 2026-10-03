# Persönliche Inbox: zentraler Anschluss nach Paket B

## Vor dem Sourceanschluss festgelegt

Der tatsächliche Browser-Historienlauf erreicht weiterhin die alte globale
Glocke mit `status=unread&limit=10`. Vollständige Historienabnahme ersetzt deren
offenen Gap nicht. Domain hat abgegrenzte eigene Quellen vorbereitet und
ausdrücklich keine native Ausführung behauptet. Der Frontend-Assistent ist
sichtbar auf live/nulltoken und ausgeschaltetes Mark-all instruiert.

1. Den vorhandenen Backendplan und Phase-A1-Plan samt reinen DTOs,
   Readpaarmodell, Rawvalidator, SQL-Livequelle und vorbereiteten Regressionen
   in Root übernehmen. Keine zweite Neuentwicklung.
2. Modelle noch nicht in Session-/Alembic-/Startup-/Recoverymetadaten global
   registrieren. K2 bleibt tatsächlicher Head, L2 TEHA vorbehalten. Kein
   Runtime-create_all oder stilles Reparieren fehlender Readtabellen.
3. SQLUserStore und Businessquelle müssen nachweislich dieselbe physische
   SQLite-/PostgreSQL-Datenbank verwenden. Aktiver realer Actor und echte
   Portfolio-/Dispatchberechtigung entstehen aus aktuellen SQL-Accountdaten.
   Memory, fehlende Familie und abweichende Authdatenbank liefern503; keine
   Ersatzquelle, Actoroverride oder nachträglich gescannte globale Liste.
4. Counts und limit+1-Seiten lesen dieselbe aktuelle berechtigte Grundlage.
   Bestehende globale Readwerte werden nicht als persönliche Reads erfunden.
   Live/nulltoken ist ehrlich; Mark-all bleibtfalse. Einzel-Readaktion bleibt
   ebenfallsfalse bis tatsächlicher HTTP-Writer und Commitfence abgenommen.
5. Vorbereitete transaction-only stage_read verlangt einen nominellen echten
   Rootbeleg für dieselbe aktive Session/Transaktion/Target. Fehlendes Modul,
   Daten-DTOvertrag, bool oder Lambda kann keinen Write erlauben. Keinen
   schwächeren Ersatz hinzufügen, um eine Prüfung grün zu machen.
6. Zuerst den reinen Raw-/DTO-Gate isoliert ohne Appkonfiguration ausführen,
   dann die tatsächlichen eigenen SQLite-/SQLUserStore-Quellenfälle seriell.
   Vorhandene Testkonfiguration stellt immer eine eigene synthetische DB;
   kein ambient DATABASE_URL oder private .env. Jeder Gate hat ein eigenes
   Prozessbudget und Abschluss-/Poolnachweis.
7. Der Plattformagent prüft unabhängig die tatsächlichen Sid-/Account- und
   Parent-Writers/Lockorder. Erst dieser Quellenplan und echte SQLite-/PG-
   Linearisation erlauben einen neuen zentralen CommitAuthorityadapter.
8. HTTProute, öffentliche Aktivierung der Glocke, gemeinsame Migration und
   Restore-/Privacyadapter folgen dem geprüften Quellenanschluss. Keine
   Verfügbarkeit oder Produktfreigabe aus vorbereiteten Tests ableiten.

Die bestehende API bleibt währenddessen unverändert. PhaseB/C verwendet eine
explizite versiegelte serverseitige ReadSelection und den vorhandenen dauerhaften
Jobkern. Timestamp, UUID oder ein beliebiger Cursor ist kein Mitgliedschaftsbeleg.

## Geplante Abnahme des Quellenanschlusses

Reine Importgrenze, vollständige/fehlende/beschädigte Readfamilie, echte
Parentreferenzen, naive vollständige UTC-Zeit und lesende Fristprüfung.
Tatsächliche SQL-Accounts: persönliche unabhängige Counts, globalRead-Parität,
selektierte Grants, Dispatchrolle, kaputte polymorphe Paare, Resourcegrant,
Cursorbindung/Chronologie und fehlende Capability vor jeglichem Inbox-DML.
Kein behaupteter positiver Write, HTTP-, PostgreSQL- oder Browsernachweis aus
diesen ersten vorbereiteten Quellenprüfungen.

## Tatsächlicher erster Puregate

Root `62f138e`: 7 PASS/5 FAIL in1,43s, hard30, normalExit1. Positives Rawimage
wird fälschlich als beschädigtes Schema abgewiesen. Unverhüllte isolierte
Diagnose auf derselben eigenen In-memory-Testdatenbank zeigt tatsächlichen
TypeError bei `set(FIELDS) <= columns` (columns ist ein dict). Beide Raw-/
SQLInspectorzweige haben diesen Quellenfehler. Es wurden keine App/Auth/
Settings/Storemodule importiert und keine private Datenbank verwendet.

Domain ist vor Sourcefix mit präzisem Befund beauftragt: Vergleich gegen
tatsächliche Spaltennamensets in beiden Zweigen, ohne schwächere Schema-/FK-/
Zeitprüfungen. Der komplette12erPuregate muss nach der Quellenkorrektur erneut
laufen, weil vorherige Negativfälle zum Teil am unbeabsichtigten TypeError
scheitern konnten. Erst danach die sechs nativen eigenen SQL-Quellenfälle.

Beide Vergleiche sind in5dcd35a korrigiert. Vollständiger reiner12er-Gate:
12 PASS in1,23s, hard30, normalExit0; keine App-/SQLUser-/HTTP-Abnahme daraus.

Der tatsächliche eigene SQLite-/SQLUserStore-Gate auf ed70ae8 liefert5 PASS/
1 FAIL in15,08s, hard120, normalExit1. Persönliche Counts/Rollen/Scopes,
Cursorbindung/Grantwechsel, abweichende Quellen und Fakecapabilities ohne
DML bestehen. Der Zeitfall scheitert vor dem Produktaufruf an einer neuen
Fixturezeile: `dict(CursorResult)` versucht dessen Mappingprotokoll statt
Iteration und wirft TypeError. Das ist kein positiver Zeit-/NULL-Keysetbeleg.
Vor dem Fixturefix festgelegt: die tatsächlichen fünf Fixturezeilen über
`result.all()` als Rows lesen; native CURRENT_TIMESTAMP-/Mikrosekunden-/NULL-
Assertions vollständig erhalten. Danach nur diesen unvollständigen Fall
wiederholen; keine unnötige Wiederholung der fünf grünen Quellenfälle.

Gezielter Folgefall auf2e58c12: 1 PASS in5,66s, hard45, normalExit0. Damit sechs
unterschiedliche positive SQL-Quellenfälle komponiert. Pool-/eigene Session-
Aufräumprüfungen bestehen. Kein vollständiger wiederholter6er-Gate, kein
positiver Write und keine HTTP-/PostgreSQL-/Migrations-/Recoveryabnahme.

## Unabhängig geprüfter nächster CommitAuthorityvertrag

Plattformreview ist rein lesend, ohne Tests/Edits. Die vorhandene Rotation
sperrt User vor Sid. Deshalb native Reihenfolge: vorhandener auth_setup-
Managementsingleton → tatsächlicher User → tatsächliche Sid-Familie. Der
Singleton darf bei Abwesenheit nicht heimlich angelegt werden. SQLUserStore-
Managementwrite schützt dabei normalen Rollen-/Grant-/Aktivitätswechsel;
revoke/touch sperren nur Sid. Sid→User würde einen echten Deadlock ermöglichen.

Root besitzt eine frische kurze Session, dieselbe tatsächliche Auth-/Fach-
Connection und genau eine Operation. SQLite BEGIN IMMEDIATE vor jedem Snapshot;
PostgreSQL Lock-/Statementbudgets vor erstem Lock. Keine laufende oder
verschmutzte fremde Session übernehmen. In der gehaltenen Unit ausschließlich
decode_signed_token und native User/Sidprüfung; decode_token kann über touch
einen zweiten Writer starten. Legacytoken ohne Sid verlangt erneute Anmeldung
für persönliche Writes. Refreshgeneration wird nicht mit session_version
verwechselt. Rawtoken bleibt weder in DB noch Logs.

Der vorhandene operational_lock schützt auch noch nicht vorhandene
Dispatchzeilen gegen restriktiven Insert des Tickwriters. Tatsächliche
Notification-, Resourcegrant- und positiven Scopeparentzeugen müssen bis
Commit gehalten werden. Parentprüfung übernimmt zentralen Alias-/CSV-/Scope-
Graph und vorhandene Location-/Measurement-/Tenantgrenzen. Nach wartenden
Locks Elternbindung erneut lesen; geänderter Pfad ergibt Konflikt. Kein
Installationsstocklock und keine vorgetäuschte generische Parentfähigkeit.
Unbelegte Zielzweige behalten mark_read=false bis zum tatsächlich geprüften
eigenen Anschluss.

Der konkrete NotificationReadCommitAuthoritybeleg entsteht ausschließlich im
Rootwrapper und ist gegen dessen Ausstellerregistrierung identitätsgeprüft:
genaue Session/SessionTransaction/Connection, Actor/Sid/Principal, Operation,
Notification-ID und tatsächlich gehaltene Fences. Savepoint-/Targetwechsel,
beendete/fehlerhafte Transaktion und Wiederverwendung sind unzulässig.
Der DTO ist kein Beleg. Wrapper prüft nach Flush und nach allen Wartezeiten
Credential-/Familienablauf, Konto, vollständige Principal-/Targetbindung
unmittelbar vor Commit. Keine spätere Fachaktion vor Commit. Ein Sessionhook
verweigert einen verfrühten Commit, ersetzt die explizite Abschlussprüfung aber
nicht. Domainstage_read besitzt weiterhin weder Commit noch Rollback.

Native Raceprüfungen müssen beide wirklichen Reihenfolgen beweisen: Änderung
gewinnt zuerst → kein Read; Read hält Fences zuerst → Änderung erst nach Read-
Commit. Danach HTTPpublish-Verweigerung darf nicht als Rückrollen eines schon
geordneten Commits beschrieben werden. Wiederholung bleibt insert-once.
TEHA braucht eine eigene Capability auf demselben Account-/Sidkern, kein
Notificationbeleg und keine Providerkontakte innerhalb der DB-Locks.

Domain bereitet separat tatsächliche PostgreSQL-Quellenfälle vor. Eine echte
Notification-Repositoryzeit unter zwei Sessionzeitzonen wird gegen UTC gemessen,
bevor weitere Zeitdefaults verändert werden. Diese Vorbereitung startet keinen
DB-/Serverprozess und behauptet keine native Abnahme.

## Tatsächliche weitere Rootprüfungen und Quellenkoordination

PG-Vorbereitungen c0f56dc/10cf3db/10ec75d wurden geprüft und als
f5d8f2d/290c357/8703b60 übernommen. Zwei Scope-/Cursor-/Micro-/NULL-Fälle
PASS13,91s, kompletter10002-Fall/sechsWalks PASS80,00s. Echte Repositorywriter
unter Berlin/NewYork hatten2FAIL: nachvollziehbare+2h/−4h-Verschiebung im
plainDateTime-func.now-Default. Vorcodee98b2c5→Source92adf0d normalisiert nur
Notificationzeitfelder und deren SQLdefaults aufUTC; physicalDDLgleich,
SQLiteCURRENT_TIMESTAMP bleibt bestehen, keine Altzeilenumschreibung.
Native korrigierte2Zonefälle PASS11,44s, betroffenerSQLiteFall PASS9,16s,
pureZeittyp/Dialekt10PASS0,65s. Details/Grenzen/Serverabschluss im separaten
NOTIFICATION_UTC_WRITER_CORRECTION_PLAN_20261003.md. Kein persönlicher Write,
HTTP, Migration, Recovery oder vollständiger Release als Nebenbeleg.

M2 m2a2b3c4d5e6 ist für die persönliche Inbox explizit reserviert, nach
TEHA-L2 l2a2b3c4d5e6. Plattform bereitet die genaue additive Readonly-HTTP-
Quelle und inaktive Revisionsvorlage außerhalb versions vor; Root entscheidet
gemeinsam über tatsächliche Aktivierung/Schemaqualifikation/Recovery/INTERNAL.
Frontend erhält den tatsächlichen Phase-A-live/null-Vertrag und genau
{notification_id,read_at} für Single-read. Keine aus der Livepage erfundene
Mark-all-Selektion oder synchroner Terminaldefault. Globale Bell bleibt bis
zur gemeinsamen echten API-/UIabnahme unverdrahtet.

TEHA-Chat hat150aa66clean übergeben und die tatsächliche Gesprächslängengrenze
erreicht. Unabhängiger Readonlyreview fand vier konkrete offene Grenzen:
Actor-onlyAuthority ungebunden an neu erzeugte Unit; tatsächlich verändertes
unreleasedL2-Layout trotz widersprüchlicher Docs; Original-/Mappingtarget-
Kreuzbindung und Dokumenttypregel. Root hat den lokalen GPT6.1Solxhigh-Agenten
mit Vorcodekorrektur/finalemL2Freeze beauftragt. Kein bestehendes LiveL2
angenommen, kein privates Schema verändert, keine Aktivierungsfreigabe.

Readonly-Paket608890c/d543aad/72c0756 ist inzwischen unabhängig übernommen
und gezielt ausgeführt: 9HTTP PASS44,95s/hard120, 8RawRecovery PASS1,13s/hard30,
6SQLiteOperations PASS1,46s/hard60, jeweils Exit0 und abgeschlossene Prozesse.
Die fünf PG-Migrationsfälle wurden ausdrücklich abgewählt, nicht abgenommen.
Der kleine HTTPaufbau ist kein Produktionscoldstart und der Operationslauf
kein entdeckter L2→M2-Head. Globale Registrierung/INTERNAL/Start/Restore und
positiver Sid-gebundener Single-read bleiben bis zur gemeinsamen Prüfung offen.
PG-Operationsfixture wird vor ihrem nativen Lauf auf ausschließlich explizite
disposable Testziele, endliche Budgets und vollständiges Setupfailure-Cleanup
gehärtet. Der tatsächliche native CHECK-Katalogvertrag bleibt ebenfalls offen;
ein gültiger aktueller Bestand allein beweist keine vorhandene CHECKwirkung.
