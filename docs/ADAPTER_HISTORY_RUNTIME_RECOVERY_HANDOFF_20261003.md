# Adapterhistorie – Runtime/Recovery/Reset Handoff

Checkout: `work/integration-history-runtime`, Branch
`assist/integration-history-runtime-recovery`. Ausgangsbasis dieses Dirty-
Checkouts war `4eb7d0af868bf692adf6a479057797723b1e035a`.

## Verbindliche Voraussetzungen / Integrationsreihenfolge

Root muss vor diesen Runtimecommits die beiden gerade gelieferten
Manager/Fence-Folgecommits übernehmen:

1. `fc45b3ca8423ba58b1444f705a3eff0024df0219`
2. `0fb5978502c6fa43120cb2142efb1e6e25b98032`

Insbesondere `0fb5978` ist funktional erforderlich: `history_fence()` muss
bewusste Caller-`ValidationError`-/DBAPI-Ausnahmen unverändert durchlassen.
Ohne diesen Prerequisite würde der korrekte Retention-Abbruch am
Context-Ausgang fälschlich zu `HISTORY_CORRUPT` umgedeutet.

Für die Runtime-Gates wurde deshalb vorübergehend exakt
`history_store.py` aus `0fb5978` in diesem isolierten Checkout eingesetzt.
Vor dem Commit wurde diese temporäre Datei wieder auf den lokalen Parent
zurückgesetzt; die Runtimecommits duplizieren den Manager/Corefix **nicht**.

## Runtime / Konfiguration

Neue Settings, jeweils positive Work-Budgets und **keine**
Run-/Jahres-/Bestandsgrenze:

- `INTEGRATION_HISTORY_ARTIFACT_BYTES` – Default 16 MiB
- `INTEGRATION_HISTORY_PAGE_BYTES` – Default 32 MiB
- `INTEGRATION_HISTORY_TEMP_BYTES` – Default 512 MiB
- `INTEGRATION_HISTORY_TIMEOUT_SECONDS` – Default 60 s

Boolesche, nichtpositive, nichtendliche bzw. für Bytefelder nichtganzzahlige
Werte werden abgewiesen. Offline-Recovery baut `HistoryLimits` ausschließlich
aus der archivierten Konfigurationsmap; Ambient Settings/.env werden dort nicht
konsultiert.

Die History verwendet dieselbe echte `DATABASE_URL` auch bei Memory-
Fachdatenmodus; es gibt keinen RAM-Journalfallback. SQL clear_all lässt die fünf
Historytabellen unangetastet.

## Retention / Reset / Teiltransfer

`recovery_history.py` unterscheidet:

- Fakten: Runs, Events, Chunks → blockieren Geschäftsreset/Subsetoperation;
- technische Heads + Clear-Audits → bleiben erhalten, blockieren nach
  ausdrücklichem Clear nicht dauerhaft.

Memory-Reset und Memory-Import besitzen eine ausdrückliche
`memory_history_boundary`. Für SQLite ist die Reihenfolge:
**echter SQL Writer → Accountmutex → Domain-RLock**; SQL-Barriere bleibt bis
zur tatsächlichen Memory-Veröffentlichung bzw. SQL-Transaktionsbeendigung
gehalten. PostgreSQL verwendet Account/Domain vor der Historybarriere.

SQL-Retention prüft Caller-pending History-ORM-State ohne Autoflush/Commit und
recheckt hinter der bereits vorhandenen Writergrenze. Die fünf Historytabellen
werden beim SQL-Business-reset explizit übersprungen.

## Vollrecovery

- vollständige Legacyarchive ohne Historyfamilie bleiben kompatibel;
- teilweise Familie fail-closed;
- vorhandene Familie wird mit archiviertem Schlüsselring, AAD und archivierten
  Budgets vollständig offline geprüft;
- Prüfung geschieht vor File-Rebase, Restore-Claims, Sessionentzug und
  Sicherheitsrotation;
- `execution_started` ohne terminalen Abschluss wird beim Restore lediglich
  als `outcome_uncertain` normalisiert; kein Provideraufruf und kein Replay;
- Normalisierung, Job-Claimreset und Sessionwiderruf befinden sich in derselben
  caller-owned Offline-Transaktion; ein später Fehler rollt alle Änderungen
  gemeinsam zurück.

## Testkorrektur während der Abnahme

Die Runtimefixture registrierte zwei lazy geladenen Tabellenfamilien erst
**nach** `Base.metadata.create_all`, wodurch SQL-`clear_all` auf
`rent_generation_results` traf, das im synthetischen DB-Schema nicht existierte.
Die Fixture importiert nun Bank-/RentBatch-Modelle vor create_all. Ebenso werden
AuthSession/AuthRefresh-Modelle vor create_all registriert, damit der
"späterer Sicherheitsfehler → gesamter Rollback"-Gate tatsächlich die
Session-DML erreicht. Das sind ausschließlich Testregistrierungen, keine
Produkt-/Assertabschwächung.

## Tatsächlich ausgeführte Gates

Alle folgenden Runtime-Gates liefen gegen die zusammengesetzte Voraussetzung
`0fb5978`; PostgreSQL nutzte
`postgresql://immo_ci@127.0.0.1:58112/immo_ci` ausschließlich über die
vorhandenen `journal_engine`-Fixtures mit zufälligen
`integration_history_<uuid>`-Schemas. `public` wurde nicht als Testziel
beschrieben.

Die 58 Fälle der Runtime-Datei wurden vollständig in disjunkten Gruppen
ausgeführt:

- tatsächliche Runfakten blockieren Memory/SQLite/PG Reset, Export und beide
  Importmodi: **3 passed**;
- Heads/Clear-Retention, Pending-DML und Offline-Proof+Late-Rollback:
  **8 passed, 1 skipped** (Memory-Skip nur für caller-owned SQL pending ORM);
- falscher Schlüssel/AAD/Budget, ungültige Settingsbudgets und ambient-freie
  Offline-Limits: **30 passed**;
- Runtime-Startup + Partial-Family-Gates: **4 passed**;
- echte verschlüsselte Vollbackup-/Restore-Roundtrips, Legacy ohne Familie und
  falsche Archivkonfiguration vor Veröffentlichung: **6 passed**;
- ereignisgesteuerte native SQLite-Memory-Reset-Reihenfolge und echter
  PostgreSQL-Resetfence: **2 passed, 4 skipped**; Skips sind jeweils die
  absichtlich unpassenden Parameter-Modi.

Gesamtabdeckung der Datei damit: **53 passed, 5 expected skips** über 58
parametrisierte Fälle. Keine Sleeps dienen als Synchronisationsbeweis.

Statisch nach Wiederherstellung der lokalen Prerequisite-Datei:
- Ruff auf allen geänderten Runtime-/Recovery-/Testdateien: **grün**;
- Mypy auf `recovery_history.py`, `recovery_sessions.py`,
  `full_recovery.py`, `data_transfer.py`, `settings.py`:
  **Success: no issues found in 5 source files**;
- `git diff --check`: **grün**.

## Bekannter Integrationskonflikt: DDL-freier Startup

Der native Plattform-Agent bearbeitet laut Root parallel einen DDL-freien
Produktionsstart. Dieser Checkout enthält bereits ältere Dirty-Startupänderungen
in insbesondere:

- `backend/db/session.py`
- `backend/dependencies.py`
- `backend/db/migrations/env.py`
- zusätzlich Settings/.env/CI-Registrierung

Diese Änderungen wurden auftragsgemäß erhalten und geprüft, aber **nicht als
endgültige DDL-freie Rootarchitektur behauptet**. Root soll bei Integration die
Plattformlösung für Produktionsstartup priorisieren und die History-
Konfiguration/Partial-Family-Fail-closed-Grenze aus diesem Paket erhalten.
Migration d2 bleibt Core; es wurde keine neue Migration angelegt. Billing e2
bleibt separat.

Keine Liveprovider, Privatdaten, Root/Main/Preview-, UI-, AI-, Bank- oder
Workflowänderungen gehören zu diesem Paket.
