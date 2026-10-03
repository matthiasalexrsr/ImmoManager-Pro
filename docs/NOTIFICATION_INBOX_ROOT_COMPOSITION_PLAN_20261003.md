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
