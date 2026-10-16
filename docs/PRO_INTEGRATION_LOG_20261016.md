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

## Paket 3: DATEV und neutrale Jahressteuerquellen

Quelle: unveränderter Arbeitsbaum `pro-finish-tax-20261016` ab c16e0970; zwölf getrackte Dateideltas und 28 neue Dateien. Die Konflikte in Routing, Geschäftsdaten-Snapshot und Vollbackup wurden unter Erhalt beider Verträge zusammengeführt. Ein vorbereiteter ersetzender Teilimport prüft nun auch am endgültigen Memory-/SQL-Schreibpunkt erneut auf inzwischen entstandene Bank- und Steueroriginale. Der Finanz-Snapshotvalidator bleibt enthalten.

Die Offline-Restoreprüfung mit ausschließlich archivierten Schlüsseln prüft Bankoriginale, FinTS-Zustände und Steuerquellen jetzt sowohl auf SQLite als auch auf PostgreSQL. Diese semantische Prüfung findet auch beim direkten Restore vor der endgültigen SQLite-Dateipublikation statt; ein reines Steuerarchiv ohne Bankzeilen wird nicht mehr übergangen. Byte- und Geldsummenorakel bleiben maßgeblich.

Neue reine Merge-Revision `e1f0a1b2c3f3` verbindet `e1f0a1b2c3f2` und die unveränderte Steuerrevision `e160a1b2c303`. Die Paketdokumentation benennt echte lokale Restarbeiten (WISO-Serializer, dauerhafte Exportjobs, DATEV-Beleglink) und externe Zielimporte; sie gelten durch den Import nicht als abgeschlossen. Gemeinsame Prüfungen werden nach ihrem tatsächlichen Ergebnis ergänzt.

Gegenprobe `integrated-tax-restore-sql-3b499cd3940d4e7cb39df9d9d61057f9`: 35/35 bestanden ohne Skip in 110,46 Sekunden (Steuer-Vertragsfälle, HTTP, Migration/Restore und Bankmatching). Insbesondere wird ein äußerlich intaktes, aber im verschlüsselten Steuerinhalt beschädigtes Vollbackup vom öffentlichen Restore vor Veröffentlichung der Datenbank/Uploads abgelehnt. Nach diesem Lauf wurden sieben zuvor sichtbare Typfehler durch präzise Typannotation, Tabellen-Casts, geprüfte Nicht-None-Referenzen und explizite Pydantic-Eingangsvalidierung behoben; fachliche Orakel wurden nicht gelockert. Ruff und vollständiges Mypy sind Teil des folgenden Checkpoints, kein Ersatz der abschließenden gemeinsamen Matrix.

## Paket 4: dauerhafte E-Mail-Kommunikation und Empfang

Quelle: unveränderter Arbeitsbaum `pro-finish-communication-20261016` ab c16e0970. Zwölf getrackte Deltas und sechzehn neue Dateien/Verzeichnisbäume. Interne Nachrichtenfences, verschlüsselte Connection-Konfiguration, gemeinsame Quellen und manuelle Mahn-Outbox bleiben maßgeblich. SMTP-MIME mit tatsächlichen Anhängen, ausdrückliche Freigabe, DATA-Checkpoint/unknown, Jobwiederanlauf und UID-/Referenz-basierter Nur-Lese-Eingang sind Bestandteil der Übernahme.

Gemeinsame Backupkonflikte wurden additiv gelöst: Bank-, Steuer- und Kommunikationsschlüssel werden aus demselben Snapshot ermittelt. Die direkte Restore- und PostgreSQL-Probe verwenden ausschließlich tatsächlich archivierte Schlüssel. Ein im Quellpaket noch möglicher Ersatz durch Umgebungsgeheimnisse wurde hier nicht übernommen; er wäre kein portabler Nachweis. Kommunikations-MIME-Bytes werden wie Bank-/Steueroriginale vor endgültiger Dateipublikation geprüft.

Neue reine Merge-Revision `e1f0a1b2c3f4` verbindet `e1f0a1b2c3f3` und unverändertes `e160a1b2c304`. Die historische Memory-Gegenprobe zum verschobenen Thread war rot; die aktuelle übernommene Quellenauflösung wird ausdrücklich neu dagegen geprüft. Historische SMTP/IMAP-Loopbacktests sind keine externe Zustellabnahme.

Gemeinsame Kommunikationsprüfungen: `integrated-communication-memory-17ab9546047a405b88a71a4750f3492f` 40/40 ohne Skip, 56,82 Sekunden; `integrated-communication-sql-182b5c7f93b048ffa6802e7733a0877d` 43/43 ohne Skip, 238,84 Sekunden. Der SQL-Lauf enthält zusätzlich die Steuer-Restore-Gegenprobe. Beide enthalten je die sichtbare Starlette/httpx-Deprecation-Warnung. Der historisch rote Portfolio-Wechsel besteht jetzt ausdrücklich in beiden Speichermodi.

`ui-subset-1292810c47404f30ab8212a2d20ee63e`: vier tatsächliche Vitest-Dateien (Finanzpakete, Steuerexport, Kommunikationszentrale, Nachrichten-Recovery), 24/24 bestanden in 45,99 Sekunden. React-act-Warnungen in der Kommunikations-Testumgebung bleiben sichtbar; keine Fehler oder übersprungenen Fälle. Dies sind Komponententests, kein realer Browser- oder sauberer npm-ci-Nachweis.

Nach diesen Laufständen wurden 17 Typbefunde durch genaue Union-/TypedDict-Angaben, getrennte Connectionnamen und ausdrückliche Nicht-None-Prüfungen korrigiert, ohne Fachassertionen zu entfernen. Ruff für das Backend und Mypy für 507 Quelldateien bestanden danach. Die spätere Gesamtmatrix muss die endgültigen Bytes erneut prüfen; die früheren Laufhashes werden nicht umetikettiert.