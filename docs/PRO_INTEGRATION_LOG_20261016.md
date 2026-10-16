# Zusammenführung der vollständigen PRO-Handoverpakete – Integrationsprotokoll

## Arbeitsgrenze

Neuer getrennter Integrationszweig `pro/full-handover-20261016`,
Checkout `work/pro-full-handover-20261016`, Ausgang `4a9dc388`
(Connection-/Run-/Archiv- und Restoreblock). Kein Reset, kein Anwenderdatenzugriff,
kein Test auf Ports 8000/8765, keine Hauptintegration, keine Auslieferung.
Alle Paket-Worktrees `pro-finish-*-20261016` werden nur gelesen; ihre
Änderungen bleiben unverändert und uncommittet, solange ihre eigenen
Bearbeiter/Abnahmen sie nicht freigeben. Ein übertragenes Paket ist zuerst
ein Integrationscheckpoint, keine Releasefreigabe.

## Paket 1: Bankimports, MT940/CAMT/FinTS, Buchungsvorschau und Matching

Quelle: `work/pro-finish-bank-20261016`, Basis `c16e0970`.
Zehn getrackte Dateideltas wurden per Git-Dreiweg-Patch importiert,
28 neue Dateien bytegleich übertragen. Der gemeinsame Fullbackup-Konflikt
wurde fachlich zusammengeführt, statt eine Seite zu überschreiben:
verschlüsselte Connection-/Attempt-Archive und Bankoriginale werden im
extrahierten Restorestand jeweils mit ARCHIVSCHLÜSSELN geprüft.
Andere Kerndeltas (Rechte, Geschäftsdatenexport-Sperren, Bankquellschutz,
Legacy-Import und Booking-UI) wurden ebenfalls beibehalten.

Additive Migration `e160a1b2c301` bleibt unverändert ab
`d73f2b9a041c`; der schon vorhandene Connection-Versuchsbeleg-Head
`e160a1b2c300` wird durch die neue reine Merge-Revision
`e1f0a1b2c3f1` verbunden. Es wurden keine Migrationen auf
den laufenden Installationen ausgeführt. Die Migration ist kein
Konten-/Buchungsdatenreset.

Die bisherigen synthetischen 61/61 SQLite-Tests des Bankquellcheckouts
sind Vorprüfungen, noch KEIN Test der zusammengeführten Version.
Die integrative Ruff-/Mypy-Prüfung für 462 Backenddateien ist bestanden;
fünf ursprüngliche Test-Typisierungsfehler wurden korrigiert, ohne
Testorakel oder Produktcode zu lockern.

Ein echter FinTS-HBCI/PIN-TAN-Test benötigt optional `fints==5.0.1`
in separater Umgebung mit passenden Constraints, außerdem autorisierte
Bankzugänge, Produktkennung und Testbankverfahren. Der Quellworker
kennzeichnet dieses externe Provider-/Bibliotheksgate ausdrücklich
als fehlenden Nachweis. Der Banklesemodus ist keine Zahlungsanweisung.

## Weitere Pakete

Weitere zwölf beziehungsweise vierzehn zugeordnete Paket-Worktrees
enthielten bei Start unterschiedliche Arbeitsstände, einige
waren uncommittet und manche noch ohne Codeänderungen. Die
ursprüngliche Pflichtmatrix in `docs/PRO_COMPLETE_REQUIREMENTS_20261015.md`
bleibt die unveränderte Referenz. Keine dieser Positionen
wird durch eine grüne Bank-/Connection-Prüfung automatisch erledigt.

Jeder neue Paket-Import wird hier ergänzt: Quellstand, Dateikonflikte,
gemeinsamer Schemahead, reale Prüfungen nach dem Import, externe Nachweise
und erst danach eigener Commit und Freigabestatus.

## Paket 2: gemeinsame Forderungsreste und Finanzberichte v2

Quelle: unveränderter Arbeitsbaum `pro-finish-finance-20261016` ab c16e0970. 31 getrackte Dateideltas und 14 neue Dateien übernommen. Die drei Konflikte in DB-Registrierung, privaten Scope-Tabellen und Buchungslöschung wurden additiv zusammengeführt. Die Löschung hält nun den bestehenden `booking_write` und prüft darin Bankoriginalschutz, sichtbare Zahlungszuordnungen, alle Fachreferenzen und Rechnungszuordnung; kein zuvor vorhandener Schutz wurde entfernt. Bankimport und Forderungsausgleich verwenden weiterhin dieselben Buchungen/Zahlungszuordnungen.

Neue reine Merge-Revision `e1f0a1b2c3f2` verbindet `e1f0a1b2c3f1` mit unverändertem `e160a1b2c302`. Quellpakettests sind historische Vorprüfungen. Dieser Import ist bis zur gemeinsamen Gegenprobe ein Entwicklungscheckpoint, keine Freigabe. Finanzumfang und offene Zusatzgates bleiben in `PRO_PACKAGE_FINANCE_20261016.md` ausdrücklich dokumentiert.

Integrationsprüfung nach der Zusammenführung: `bank-finance-integrated-sql-59fd04d4a8b545eb84d1f8ae35fcf7c8` bestand mit 31/31 Fällen ohne Skip in 83,52 Sekunden. Geprüft wurden die neuen Finanzorakel und Migrationen sowie Bankmatching und Bank-HTTP-Grenzen auf demselben Arbeitsstand. Ruff für das gesamte Backend und Mypy für 471 Quelldateien bestanden. Eine vorhandene Starlette/httpx-Deprecation-Warnung blieb sichtbar. Das ersetzt keine native PostgreSQL-, Browser-, Last- oder gemeinsame Endabnahme.

Die neue separate Umgebung `artifacts/full-test-venv` wurde mit Basis- und FinTS-Constraints vollständig installiert (`install_exit=0`, `pip_check_exit=0`). Der tatsächliche Offline-Bibliothekstest `real-fints-library-memory-f5bc1c366d644af0b5190d6b1edfe133` bestand 1/1 in 1,06 Sekunden. Netzverbindungen sind in diesem Test ausdrücklich verboten. Dies schließt das bisher fehlende Bibliotheksgate, nicht die externe Bankabnahme.