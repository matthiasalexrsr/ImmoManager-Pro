# Dauerhafte operative Arbeitslisten – Übergabe Phase 1

Stand: 2026-10-02. Eigener Branch `assist/operational-jobs-core`, Ausgangspunkt
`51bd1d970d23e30e9e2dc20e72f300405817bdeb`. Die Implementierung folgt dem angenommenen
`docs/OPERATIONAL_RESUME_ADR_20261002.md`. Sie verändert weder den bisherigen
`operational_tick` noch dessen atomaren Catch-up-/Rollbackvertrag.

## Ausführbarer Umfang

Der additive Kern führt zwei fachliche Aufgaben aus: überfällige Geldposten und
freigegebene Korrespondenztermine. Geldposten besitzen getrennte faire Lanes für
Mietforderungen und sonstige Forderungen. Somit gibt es aktuell drei konkrete
Familien: `overdue_rent_charge`, `overdue_receivable`, `correspondence`.

Die Verarbeitung einer Korrespondenz darf nicht hinter sämtlichen Forderungen
warten. Der erste Aufruf bedient bei gleicher Priorität die Korrespondenz; weitere
Aufrufe wählen die am längsten nicht bediente bereite Lane. Gesonderte Quellen
werden mittels bestehender Dispatch-/Occurrence-Schlüssel entdoppelt. Es werden
weder Zahlungen noch Rechnungsbuchungen oder Nachrichten an externe Empfänger
erzeugt.

Der Kern ist ausdrücklich noch kein vollständiger Schedulerersatz. Wiederholte
normale Aufgaben, Mieterwechselabläufe, Müll-/Ablesepläne, Vertragserinnerungen,
Eskalationen, Archivierung erledigter Benachrichtigungen und UI-/Schedulerwiring
werden hier nicht übernommen. Vorhandene Legacyfunktionen bleiben erhalten.

## Persistenz und Transaktionen

`operational_jobs`, `operational_job_lanes`, `operational_work_items` sind die
einzigen neuen Tabellen. Der letzte Tabellentyp enthält zugleich unveränderliche
CAS-Befehlsbelege (`kind=command`, keine Lane). Erstellreferenzen und indizierte
Befehlsreferenzen sind SHA-256-Digests; beliebig lange legitime externe Referenzen
laufen daher nicht in die PostgreSQL-Btreegrenze. Der Befehlsbeleg behält die
ursprüngliche Anfrage und exakt die ursprüngliche Antwort.

Ein Paket hat getrennte dauerhafte Planungs- und Veröffentlichungstransaktionen:

1. Lane übernehmen, neue Token/Fence/Lease und fairen Bedienungsstand speichern.
2. Eine begrenzte SQL-Keysetseite bestimmen. Cursor und geplante Quellen gemeinsam
   committen, während der Claim weiter gilt. Unveränderte oder bewusst gelöschte
   frühere Ziele wachsen nicht bei jedem neuen Lauf erneut zur Arbeitsliste an.
3. Quellen erneut laden und prüfen, höchstens die positive Paketmenge ausführen.
   Geschäftsziele, vorhandenes Deduplizierungsjournal, Eintragsergebnisse und Zähler
   committen gemeinsam, erst nach abschließender bedingter DB-Fenceprüfung.

Alle Quellenabfragen verwenden SQL-Prädikate, Schlüsselgrenzen und `LIMIT`.
Bestandslisten werden nicht mittels `getAll` oder einer ersten 10.000er-Teilmenge
abgebildet. API-Resultate enthalten kleine Lane-Zähler und eine separat paginierte
Arbeitsliste, keine wachsenden Ziel-ID-Arrays. Die internen Seitengrößen und Zeiten
sind Paketgrenzen; die Gesamtsumme von Quellen oder Fortsetzungen ist unbegrenzt.
Das weiche Zeitbudget lässt eine erste Quelle passieren, damit langsamere erste
Abfragen nicht dauerhaft leere Pakete erzeugen. Die harte Leasegrenze bleibt
unangetastet. `available_at` in UTC nennt je Lane früheste Wiederholung bzw.
Leaseübernahme, ohne interne Tokens preiszugeben.

SQL arbeitet immer mit einer eigenen Session und committet keine offenen
Änderungen der Session des Aufrufers. Die Memoryvariante protokolliert nur
veränderte Datensätze zur Rücknahme und kopiert keine gesamten Sammlungen.
Die bestehende operative globale Sperre bleibt für diese kurzen Pakete bestehen,
um mit Legacyticks dieselben Deduplizierungsjournale sicher zu teilen. Mehrere
Worker können Claims übernehmen und fortsetzen; Veröffentlichungstransaktionen
sind derzeit über diese Sperre serialisiert.

Ein zwischen Planung und Ausführung bezahlter Geldposten wird erneut geprüft und
zum No-op. Fehlende Originalziele mit erhaltenem Journal bleiben Tombstones.
Veraltete freigegebene Korrespondenz markiert einen vorhandenen Termin als
veraltet, verschiebt jedoch sein ursprüngliches Datum nicht. Die bestehende
Korrespondenzprüfung der Originalquellen und Rechte wird verwendet.

Dieser Lauf ist kein vollständiger historischer Datenbanksnapshot: Neue oder
zwischenzeitlich berechtigte Quellen hinter dem gespeicherten Cursor benötigen
einen neuen Lauf mit neuer Erstellreferenz. Noch nicht abgearbeitete geplante
Quellen werden gegen den aktuellen Datenstand geprüft. Die Startobergrenze ist
eine stabile Quell-ID-Grenze, kein Stocklimit.

## Rechte, Fehler und Wiederaufnahme

Ein ausdrücklich benannter aktiver Eigentümer bzw. Verwalter mit Zugriff auf
alle Portfolios ist erforderlich. Ein Job ist an Benutzer und dessen gesamten
Berechtigungsstand gebunden. Rechte werden frisch am Anfang und kurz vor dem
Commit geprüft. Eine installierte globale Scheduleridentität muss dieselben
Prüfungen erfüllen; ein anonymer oder impliziter Systemaktor existiert nicht.

Nach Leaseablauf erhöht eine Übernahme den Fence. Alte Worker dürfen ihre
geplanten oder veröffentlichten Pakete nicht committen. PostgreSQL verwendet
`timezone('UTC', clock_timestamp())`, keine eingefrorene Transaktionsanfangszeit
und keinen Zeitvergleich in einer abweichenden Sitzungszeitzone. PostgreSQL-
Lock-/Statementtimeouts werden vor dem ersten Authlock gesetzt.

Rechteentzug erzeugt `actor_changed` und einen Zustand `attention`. Dauerhafte
Quellfehler einschließlich Integritätsverletzungen betreffen nur das aktuelle
Paket; andere gültige Einträge und Lanes können weiterlaufen. Ein bekannter
fehlerhafter Eintrag bleibt gezielt wiederholbar. Temporäre operative
Datenbankfehler erhalten `transient_database` und eine gespeicherte Verzögerung.
Wenn die Datenbank auch die Fehleraufzeichnung verhindert, bleibt die Lease zur
späteren Übernahme erhalten. Der additive Router gibt in diesem Fall eine sichere
503-Antwort mit `database_unavailable` und `Retry-After` zurück, keine Treiberdaten.

`cancel`, `retry` und `retry_lane` benötigen eine positive erwartete Jobrevision
und eine Befehlsreferenz. Stale Revisionen scheitern mit 412; Wiederholung derselben
unveränderten Anfrage gibt denselben Receipt zurück. Andere Eingaben unter
derselben Referenz scheitern mit 409. Abbruch erhöht Fences und entfernt Claims,
bereits erfolgreich veröffentlichte Ziele bleiben erhalten. Ein neuer Actor oder
ein anderer Rechteumfang übernimmt historische Jobs nicht stillschweigend.

## Additiver API-Vertrag

Der Router ist absichtlich noch nicht in der Produktionsanwendung registriert.
Bei Registrierung unter `/api/v1` ergeben sich:

| Methode | Pfad unter `/api/v1/tasks/operational-jobs` | Funktion |
|---|---|---|
| POST | leer | Job erstellen bzw. mit identischer Referenz wiederholen |
| GET | `/{job_id}` | Kompakter Fortschritt |
| POST | `/{job_id}/continue` | Nächstes faires Paket ausführen |
| POST | `/{job_id}/cancel` | Abbruch mit CAS-Beleg |
| GET | `/{job_id}/items?after=…&page_size=…` | Keysetseite der Quelleinträge |
| POST | `/{job_id}/items/{item_id}/retry` | Fehlerhaften Eintrag wieder aufnehmen |
| POST | `/{job_id}/lanes/{lane_id}/retry` | Planung/Rechteproblem bewusst wiederholen |

`JobCreate`: `idempotency_key`, `as_of`, positive `lookback_days`/`days_ahead`,
optional explizite, eindeutige Familien. `JobContinue`: strikt positive ganze
`max_items`, keine Obergrenze. `JobCommand`: `idempotency_key` und strikt positive
ganze `expected_revision`. `PacketPolicy` ist interne Konfiguration für positive
Seitengröße sowie endliche positive Paket-/Leasezeiten.

## Pflichten der Integration durch Root

1. Migration `c2a2b3c4d5e6` ist hier isoliert nach `a2a2b3c4d5e6` eingehängt. Bei
   Integration an die tatsächlich vorgelagerte P1-Revision `b2…` rechainen und
   reale Alembic-Auf-/Abstiegsprüfung wiederholen. Der Downgrade verweigert das
   Entfernen irgendeiner belegten neuen Tabelle.
2. Modellregistrierung, vollständige Produktions-DDL-/Revisionsprüfung und
   `install_job_guards` in alle relevanten Laufzeit-/Restorepfade aufnehmen.
   Die explizite Setuphilfe ist kein stilles Nachmigrieren im Service.
3. Alle drei Tabellen zusammen in Backup, Restore, Serverrestore, SQLite-
   Wartungsersatz, Reset-/Seed-Schutz, Portfoliogrenzen und SQL-Memory-Parität
   berücksichtigen. CAS-Befehlsbelege dürfen generische Löschpfade nicht verlieren.
   Rowtriggers ersetzen keinen Schutz vor privilegiertem PostgreSQL-TRUNCATE.
4. Den reinen Helfer `validate_job_journal(connection, deadline=…)` vor
   Veröffentlichung eines Restorebestands aufrufen. Vollständig alte Bilder ohne
   diese Tabellen liefern `False`; eine teilweise Familie ist ungültig. Der Helfer
   prüft quellgebundene Journalreferenzen und streamt den Bestand.
5. Ausschließlich offline im noch nicht veröffentlichten Restorebestand
   `reset_restored_job_claims(connection, deadline=…)` innerhalb derselben äußeren
   Transaktion aufrufen: vollständig validieren, Fences erhöhen, Leases entfernen,
   Wartezeiten bereiter Arbeit zurücksetzen und Jobrevisionen erhöhen. Der Helfer
   committet nicht und greift auf keinen Benutzer-/Liveservice zu. Äußere
   Restorefehler müssen diese Änderungen ebenfalls zurückrollen.
6. Router, Hintergrundaufrufe und UI erst dann aktivieren. `attention` sichtbar
   machen und nach fachlicher Korrektur mit aktueller Berechtigung explizit
   wiederholen. `available_at` verhindert unnötige Wiederholungen bei aktiver
   Lease bzw. gespeicherter Verzögerung. Weitere fachliche Familien und globale
   Jobauswahl sind gesonderte folgende Phasen.

## Prüfbericht

Echte Memory-/SQLite-Fälle sind unabhängig von der globalen Testkonfiguration
parametrisiert. Die folgenden beiden vollständigen lokalen Gruppen wurden auf
dem finalen Produktionscode ausgeführt, jeweils mit Exit 0:

| Konfiguration | Ergebnis | Laufzeit | Log im übergeordneten Arbeitsverzeichnis |
|---|---|---|---|
| Normale lokale Testkonfiguration | 93 bestanden / 7 übersprungen | 174,22 s | `work/operational-jobs-final-memory.log` |
| `TEST_STORE_BACKEND=sql`, `SQLITE_PERSISTENT_STORE=true`, `ALLOW_INMEMORY_FALLBACK=false`, ohne `DATABASE_URL` | 93 bestanden / 7 übersprungen | 178,37 s | `work/operational-jobs-final-sql.log` |
| Reales PostgreSQL 16.15, separater dedizierter lokaler Testserver | 3 bestanden, kein Skip | 26,33 s | `work/operational-jobs-postgres-real.log` |

Die sieben lokalen Skips sind vier ausschließlich für SQL sinnvolle Varianten
im parametrisierten Memorylauf sowie die drei gesonderten PostgreSQLfälle.
Der echte PostgreSQLlauf hat diese drei Fälle anschließend geprüft. Jeder PG-
Test verwendet ein eigenes zufälliges Schema und keine bestehenden Anwendungs-
oder Publicdaten. `SELECT version()` bestätigt `PostgreSQL 16.15, compiled by
Visual C++ build 1944, 64-bit`. Die endgültige PG-Prüfung erzwingt eine reale
Sitzungszeitzone `Pacific/Honolulu`, überschreitet mit `pg_sleep(2.1)` die
2-Sekunden-Lease innerhalb der Veröffentlichungstransaktion und weist deren
Rollback mit erhaltenem Plan nach. Der PG-Receipttrigger wurde ebenfalls durch
eine tatsächliche verbotene DML-Änderung geprüft.

Die vollständige lokale Gruppe lautet:

```powershell
python -m pytest -q backend/tests/test_operational_jobs.py backend/tests/test_operational_jobs_http.py backend/tests/test_operational_jobs_migration.py backend/tests/test_operational_jobs_postgres.py backend/tests/test_operational_schedule.py backend/tests/test_correspondence_calendar.py
```

Der separate echte Serverlauf lautet:

```powershell
$env:TEST_SERVER_DATABASE_URL = 'postgresql://immo_ci@127.0.0.1:58112/immo_ci'
python -m pytest -q backend/tests/test_operational_jobs_postgres.py
```

Dieser Server ist ein ausschließlich lokaler, synthetischer Dienst. Die Gates
bleiben optional für normale lokale Läufe ohne expliziten dedizierten Server.
Der bestehende Starlette-Testclient gibt eine DeprecationWarning zur installierten
HTTP-Clientbibliothek aus; es gab keine Testfehler.

Ruff auf allen zehn neuen Pythondateien: vollständig grün. Mypy jeweils mit
Python-Zielversion 3.11 und 3.12: `Success: no issues found in 6 source files`.
Geprüfte Produktionsdateien sind die drei Servicemodule, das ORM-Modul, der
unregistrierte Router und die Migration. Beispiele für die direkten Aufrufe:

```powershell
python -m ruff check backend/db/operational_job_models.py backend/services/operational_job_types.py backend/services/operational_job_validation.py backend/services/operational_jobs.py backend/routers/operational_jobs.py backend/db/migrations/versions/c2a2b3c4d5e6_operational_jobs.py backend/tests/test_operational_jobs.py backend/tests/test_operational_jobs_http.py backend/tests/test_operational_jobs_migration.py backend/tests/test_operational_jobs_postgres.py
python -m mypy --python-version 3.11 backend/db/operational_job_models.py backend/services/operational_job_types.py backend/services/operational_job_validation.py backend/services/operational_jobs.py backend/routers/operational_jobs.py backend/db/migrations/versions/c2a2b3c4d5e6_operational_jobs.py
python -m mypy --python-version 3.12 backend/db/operational_job_models.py backend/services/operational_job_types.py backend/services/operational_job_validation.py backend/services/operational_jobs.py backend/routers/operational_jobs.py backend/db/migrations/versions/c2a2b3c4d5e6_operational_jobs.py
```

Nachgewiesene Fälle umfassen 124 offene Mietforderungen plus drei sonstige
Forderungen und ein echtes freigegebenes Originalschreiben mit Paketbudget 7,
Fortsetzung nach Claimverlust, tatsächliche zwischenzeitliche Zahlung als No-op,
Kalendertombstone/veraltetes Originaldatum, verspäteten Rechteentzug, verspätete
finale Leaseprüfung, permanenten/transienten Paketfehler mit gezielter Fortsetzung,
unveränderte Folgeläufe ohne weitere Quelleinträge, offene Quelle hinter 10.003
bezahlten SQL-Zeilen, Source-/Receiptintegrität, staged Restore vor Claim-DML,
eigenständige SQL-Sessions, reale JWT/RBAC-Routergrenzen und sichere
Outageantworten. Legacytick und bestehende Korrespondenzkalenderfälle wurden
mitgeprüft. Frontend, Vorschauprozess und laufender Produktserver wurden nicht
gebaut oder verändert. Diese Backendprüfung ersetzt keine Browserprüfung der
erst später zu integrierenden UI-/Schedulerfunktionen.
