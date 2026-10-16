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
