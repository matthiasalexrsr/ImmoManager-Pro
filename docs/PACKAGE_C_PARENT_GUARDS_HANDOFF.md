# Paket C5: gewöhnliche Elternschreiber und Datenschutzkomposition

Eigener Checkout `work/measurement-parent-guards`, Basis `bc90599`.
Übernahmefolge: `b51c4bc` (Plan), `6713d89` (gewöhnliche Elternschreiber),
`d760dae` (Personenprojektion und Privacyfence), danach dieser Handoffcommit.
`61ade23` ist der getrennte Widerspruchsplan und enthält keine Produktänderung.

## Tatsächlich geschützter Weg

SQL-Repository PUT/PATCH/DELETE und direkte Repositoryaufrufer nehmen vor
Lifecycle-Elternsperren die gemeinsame Messimmobiliensperre. Memory führt den
gleichen Schutz vor Mutation/Kaskade unter Account-/Domain-Sperre aus.
Originalbezüge von Portfolio/Immobilie/Einheit/Vertrag/Schlüssel bleiben erhalten;
Löschungen prüfen außerdem Mieter/Zähler/Dokumentbelege. Zurückgenommene
Quellen bleiben Originale. Bezeichnungen bleiben bearbeitbar und die heutige
Zählerzuordnung darf wechseln. Eine bereits falsche Parentbindung lässt sich
ausschließlich zu allen übereinstimmenden erhaltenen Originalbindungen reparieren.
Keine Historie wird dabei überschrieben.

Frische Rolle/Scope/Request-Credential werden beim gewöhnlichen Schreiber bis
zum tatsächlichen Commit geprüft. Der native Gegenbeleg entzieht die Rolle
nach real ausgeführtem SQL-UPDATE und beweist vollständigen Rollback.

Personenexport und Vorschau enthalten exakt eigene eingefrorene Belegungsfakten,
deren Originalbelege und minimale Befehlsmetadaten. Der gemeinsame Request mit
Nachmieterdaten wird nicht ausgegeben. Privacyconfirmation schützt auch eine
gleichzeitig erst entstehende Messquelle; neue Quellen machen einen alten
Planhash ungültig. Memory normalisiert die neue ORM-Familie nach Inhalt.

Der abschließende Restlauf fand einen zusätzlichen Kompositionsfehler: eine
vorhandene, aber leere Messfamilie durfte bei verborgenem historischen
Workflowteilnehmer nicht vor dem alten Workflow-Scopecheck einen Tenantlookup
erzwingen. Der eigene Messfence prüft nun echte Referenzen und Scope über
Existenzbits und ruft die Detailprojektion nur bei tatsächlich vorhandenen
Messfakten auf. Fremde Originale bleiben damit geschlossen; es werden keine
vertraulichen IDs/Inhalte zurückgegeben.

## Ausgeführte Nachweise

Nur synthetische Daten; PostgreSQL ausschließlich zufällige eigene Schemas
auf `127.0.0.1:58112`. Keine Änderung an public oder am Dienstlebenszyklus.

| Nachweis | Tatsächliches Ergebnis |
|---|---|
| Eigene native Eltern-/Rechte-/Privacyfälle auf Memory, migriertem SQLite und PostgreSQL | 15 passed, `work/measurement-parent-native.log` |
| Reparierbare Originalbindung plus native Regression | 9 passed, `work/measurement-parent-repair.log` |
| Privacyconfirmation gegen erste parallele Quellenbestätigung | 3 passed, `work/measurement-parent-privacy-race.log` |
| PUT und Rechteentzug nach echtem SQL-UPDATE | 5 passed, 1 gezielter Memoryskip, `work/measurement-parent-publication.log` |
| Tatsächliche SQLite-Schreibsperre | 1 passed, 2 backendbedingte Skips, `work/measurement-parent-busy.log` |
| Größerer bestehender Regressionlauf bis Legacy-Abwesenheitsfixture | 446 passed, 41 skipped, 1 Fixturefehler; `work/measurement-parent-regressions.log` |
| Abschließende 24 Parameterfälle ab kompletter Legacyabwesenheit nach beiden Fixes | 14 passed, 10 backendbedingte Skips, 53,93s; eigener `measurement-parent-final24-composed.log` |
| Ruff auf finalem Messgraph und Privacyfixture, `git diff --check` | grün |

Die alte Legacyfixture hatte den neuen leeren Schedulerstate noch vor dem
referenzierten operational_jobs stehen. Sie entfernt nun zuerst dieses konkrete
Kind, ohne CASCADE. Der abschließende Restlauf prüft komplette Abwesenheit auf
allen drei Backends, versteckte Personenreferenz, atomaren Rollback, echte lazy
Memoryjobs, Schedule-Normalisierung und beide SQLite-Accountgrenzen. Ein
zwischenzeitlicher Infrastrukturabbruch (PG Connection refused) ist dokumentiert
und im späteren Restlauf vollständig ersetzt. Kein erneuter großer Gesamtlauf
wird behauptet; Root besitzt die gemeinsame Abnahme auf dem Integrationscommit.

## Zentrale Integration und Grenzen

Root besitzt frühe Modellregistrierung, Startup, Vollbackup/Recovery,
`measurement_history_schema.py` und die neue zentrale Datenbankprüfung. Hier
werden diese Dateien nicht parallel verändert. Originale und alte
Historycheckoutdateien bleiben erhalten. Die UI und die unabhängige gemeinsame
Recoveryprüfung liegen außerhalb dieses Elternschutzpakets.

Das dauerhaft gespeicherte Widerspruchsjournal ist das eigene Folgepaket nach
`PACKAGE_C_DISPUTE_JOURNAL_PLAN.md`; dafür reservierte Root ausschließlich
`j2a2b3c4d5e6` mit Vorgänger `h2a2b3c4d5e6`. Die frühere i2-Reservierung
war falsch: i2 ist bereits eine historische Migration vor j1. Root hat den
vollständigen Graph geprüft; diese alte Migration bleibt unverändert.
Dieser Handoff behauptet keine
fertige Widerspruchsoberfläche und enthält keine solche Migration.
