# PRO-Entwicklungsstand und Codex-Übergabe – 15. Oktober 2026

## Einordnung

Der Gesamtauftrag wurde nach der unzureichenden ersten Teillieferung wieder aufgenommen. Die zuvor nicht geschriebene Nachrichtenoberfläche ist jetzt implementiert, zusammen mit SQL-Keysetseiten, kontrollierten Wiederholungsbelegen, nativen Auth-/Nachrichtenprüfungen und einer isolierten Wiederherstellungsprobe. Aktueller Paketnachweis: `PRO_MESSAGE_WORKFLOW_20261016.md`. Der ursprüngliche Bericht bleibt unverändert als `PRO_IMPLEMENTATION_PROGRESS_20261015.initial.md` erhalten. Die übrigen Pakete sind weiterhin getrennt in der Matrix geführt; es gibt noch keine Gesamtfreigabe.

## Arbeitsbasis und Schutzgrenzen

- Gerät DESKTOP-O008GV9, ID 22166494-d25d-4097-b6cf-e93b2ddfacd9: in dieser Sitzung erneut als online ermittelt und durch erfolgreiche Dateisystem-/Git-Aufrufe erreicht.
- Ausgang: 04021da57e009419ae8d07346ad890fdabad6533; zentraler Checkout bei Arbeitsbeginn sauber, Zweig codex/claude-review-20261013.
- Eigener Zweig: pro/interfaces-20261015.
- Eigenes Arbeitsverzeichnis: C:\Users\matth\Documents\Codex\2026-10-01\wi\work\pro-interfaces-20261015.
- Keine Änderung am Integrationszweig; kein Reset, keine Zusammenführung und kein Rollout. Keine Anwenderdatenmigration, kein Lesen/Kopieren produktiver Konfigurationen oder Geheimnisse. Die Ports 8000/8765 wurden nicht für Tests verwendet.
- Prüfprozesse erhalten eigene DATA_DIR-, Upload-, Backup-, Secret- und Integrationspfade sowie ausgeschaltete Scheduler. Die vorhandene Python-Umgebung wurde nicht durch Paketinstallationen geändert.
- ripgrep war im Werkzeug-PATH nicht verfügbar. Die Quellinventur verwendete deshalb lesendes git grep / git ls-files, ohne eine globale Werkzeuginstallation oder PATH-Änderung.

## Historische erste Änderungen (aktuelle Ergänzung im Paketnachweis)

### 1. Dauerhafter Sitzungswiderruf und Refresh-Claim

Commit: fe561d0a7cdbcdc4ee7b4adc1a23a1598450f5a7.

Dateien: backend/auth.py, backend/routers/auth.py, backend/services/portfolio_http.py, backend/tests/test_auth_failclosed.py.

Der SQL-Widerruf muss bestätigt sein, bevor der positive lokale Cache ergänzt wird. Fehler beim Öffnen, Lesen, Commit oder Rollback werden als HTTP 503 mit Retry-After und no-store gemeldet; SQL-Parameter und Exceptiondetails werden nicht protokolliert. Eine gescheiterte Revocationprüfung ist kein Nachweis einer gültigen Sitzung. Bereits bekannte Widerrufe bleiben ablehnbar. Der Datenbank-Lesecache erhält eine Ablaufzeit.

Logout bleibt wiederholbar. Refresh fordert mit require_unrevoked=True einen einmaligen Claim auf dem vorhandenen eindeutigen Datenbankschlüssel. Nach einer verlorenen Antwort über einen bereits gespeicherten Claim wird der alte Refresh-Token nicht erneut nutzbar; eine neue Anmeldung kann erforderlich sein. Zwei getrennte Prozesse dürfen nicht beide gewinnen. Logout mit zwei Tokens bleibt sequenziell: Scheitert der zweite Widerruf, ist die gesamte HTTP-Aktion fehlgeschlagen, der erste bestätigte Widerruf bleibt bestehen und eine Wiederholung ist zulässig. Es wird keine neue atomare Zwei-Token-Transaktion behauptet.

Die Rechte-Middleware darf einen temporären Authentifizierungsfehler nicht in einen fehlenden Akteur umwandeln und anschließend unbeschränkt fortfahren. Sie liefert jetzt den Fehler einschließlich Headern vor dem Endpoint-Aufruf. Datei-/Uploadzugriff verwendet dieselbe Widerrufsentscheidung. Bei fehlgeschlagenem Logout/Refresh wird kein erfolgreiches Cookie-Ergebnis ausgegeben.

Schema/Daten: vorhandene revoked_tokens-Tabelle und vorhandener Unique-Key; keine neue Migration, kein neues Secretformat und keine zweite Sitzungsdatenbasis. Die normale Bereinigung abgelaufener Widerrufe bleibt bestehen. Positive Logout-/Refresh-/Scope-Regressionsfälle sind Bestandteil der lokalen Prüfung.

### 2. Nachricht: Pfad und Body müssen denselben Thread benennen

Commit: ae44ab930fd1d1379ae546759d65d2ca47563cf2.

Dateien: backend/routers/messages.py, backend/tests/test_message_thread_boundary.py.

POST /api/v1/messages/threads/{thread_id}/messages prüft zunächst den berechtigten Pfadthread. Ein abweichender payload.thread_id erzeugt HTTP 422, bevor create_message aufgerufen wird. Nicht zugängliche Pfadthreads bleiben 404; übereinstimmende IDs behalten den bisherigen API-Vertrag. Es gibt keine neue Migration.

Dies schließt ausschließlich den serverseitigen Pfad-/Body-Fehler. Threadwechsel im Browser, getrennte Entwürfe, sichere späte Sendebestätigungen, dauerhafte Nachrichten-Idempotenz und SQL-Keysetseiten sind damit ausdrücklich nicht abgeschlossen.

## Prüfhistorie der ersten Teillieferung

Lokal erhaltene Protokolle liegen unter artifacts/pro-tests/. Sie enthalten ausschließlich synthetische Testfälle; sie wurden nicht als private Rohprotokolle veröffentlicht.

- Ausgangscode plus neue Backendregressionen: 11 fehlgeschlagen, 4 bestanden. Verzeichnis baseline-memory-7bda58ca808a4d46b8b331c3e46af562. Dies bleibt ein roter Ausgangsnachweis.
- Erste korrigierte gezielte Backendprüfung: 15 bestanden. Verzeichnis auth-fixed-memory-6a13aa605b89460199386c18b3b6f60f.
- Erweiterte Memory-Prüfung (Arbeitsstand vor dem Codecommit): 93 bestanden, eine Bibliotheks-Deprecation-Warnung. Verzeichnis auth-regression-memory-d2a8a58870d943f09deb0b5cd8d65fba.
- Erweiterte SQLite-Prüfung (Arbeitsstand vor dem Codecommit): 93 bestanden, eine Bibliotheks-Deprecation-Warnung. Verzeichnis auth-regression-sql-bc269929ed9840f6af0c56ef8b5d62df.
- Erneute gezielte Prüfung auf Codecommit ae44ab930fd1d1379ae546759d65d2ca47563cf2: Memory 17/17 und SQLite 17/17 bestanden, jeweils eine Bibliotheks-Deprecation-Warnung. Verzeichnisse committed-boundaries-memory-1c179af3e59946be8c17b1b71dbbaefd und committed-boundaries-sql-c32e6ed14f9b4eb09c547b809f901523. Es wurden keine Pflichtfälle übersprungen.
- Maschinenlesbare Ergebnissummen, Herkunft und normalisierte SHA256-Werte der geprüften Code-/Testdateien: docs/PRO_VALIDATION_20261015.json. Die früheren Arbeitsstandprüfungen werden nicht als unabhängige Prüfung späterer Änderungen umbenannt.
- Ruff: bestanden. Mypy --platform linux: im ersten Lauf zwei Typfehler ausschließlich in den neuen Tests; nach zusätzlichen Table-/Header-Prüfungen bestanden, 419 Quelldateien. Keine Typ- oder Testgates wurden abgeschwächt.
- Zusätzliche Frontendregressionen auf unverändertem Messages.jsx: sechs Fälle ausgeführt, sechs fehlgeschlagen; frontend-baseline.json und frontend-baseline-complete.log. Der frühere PowerShell-Aufruf wurde durch Native-Stderr-Verarbeitung unterbrochen und zählt nicht als vollständiger Lauf.
- Die sechs nicht erfüllten Frontend-Abnahmefälle sind als docs/MessagesBoundary.test.jsx.proposed erhalten. Sie sind eine separat übergebene, noch nicht integrierte Testspezifikation, keine bestandenen Produktregressionen. Bestehende Frontendtests oder CI-Konfigurationen wurden nicht geändert.

Diese Prüfungen waren in der ersten Teillieferung nicht ausgeführt. Aktuell bestehen native Auth-/Nachrichtenprüfungen, der gezielte Archiv-Restore und elf reale Browserabläufe einschließlich 10.057 Nachrichten. Die Gesamtmatrix läuft beziehungsweise enthält noch sichtbar dokumentierte Fehler; Einzelheiten und zugehörige Arbeitsstände stehen im neuen Paketnachweis.

## Historische Werkzeugbefunde – inzwischen erneut geprüft

Beim ersten Versuch war das Schreiben blockiert. In der Fortsetzung gelang ein regulärer write_file-Aufruf; der Hook und die echte Frontendverdrahtung sind jetzt vorhanden. Es wurden keine Tool-Sicherheitsregeln geändert.

Der frühere npm-ci-Versuch meldete Prüfsummenprobleme. In der Fortsetzung bestand die saubere Installation im eigenen Frontend mit Exitcode 0 und identischer Lockdatei; der neue Paketnachweis nennt das Ergebnisverzeichnis. Der nachfolgende Satz beschreibt ausschließlich die damalige Baseline: package-lock.json wurde nicht verändert. Für die isolierte Ausführung der sechs Baselinefälle wurde der vorhandene node_modules-Bestand des Referenzcheckouts in den eigenen Checkout kopiert, nicht gemeinsam beschrieben. Beide Lockdateien haben SHA256 07A5CBC9358ABE378FCECB8A45263B187AEC634DECA37443EFE65FFF6081D01B. Diese Wiederverwendung ersetzt keine erfolgreiche npm-ci-Abnahme.

## Anforderung → Implementierung → Tests → externe Abnahme → Commit → offen

| Anforderung / Paket | Implementierung und Prüfung | Commit / noch offen |
| --- | --- | --- |
| Sitzungswiderruf bei DB-Ausfall | Backend, Fehler-/Recovery-/Cookie-/Middlewarefälle sowie native getrennte Prozesse und Neustart geprüft | fe561d0a + b264cf81; gemeinsame Gesamtmatrix noch nicht freigegeben |
| Nachricht Pfad A / Body B | 422 ohne Schreiben, fremder Pfad 404; kompatibler Request-/Antwortvertrag | ae44ab93 + eb70b53c |
| Threadwechsel, Entwürfe, späte Sendebestätigung | 15 aktive Komponentenfälle bestanden; echte Browser-, Rechte-, Sendebestätigungs- und 320/360/1440-Prüfungen | eb70b53c + b264cf81; allgemeine dauerhafte Outbox separat offen |
| Nachrichten-Keyset/Großthread | Begrenzte Cursorseiten, 10.057 identische Zeitstempel vollständig, native Konkurrenz, Paket-Restore | eb70b53c; Migration c61e9a2f034b |
| Verbindungs-/Mapping-/Run-/Receipt-Rahmen | Historische Daten-/Crypto-/Managerverträge werden mit aktuellem Produkt verglichen | Nächster Implementierungsblock; noch nicht abgeschlossen |
| CSV-/MT940-Bankimport und Matching | Historische Arbeitskopien inventarisiert, nicht portiert | Offen |
| TEHA Empfang und Rückübertragung | Historische Arbeitskopien inventarisiert; keine Portalaktion | Offen; keine neue externe Abnahme |
| CAMT / lesendes FinTS | Nicht begonnen | Offen |
| Forderungsreste / gemeinsamer Ausgleich | Nicht begonnen | Offen |
| Leistungsperiodenergebnis | Nicht begonnen | Offen |
| DATEV | Historischer Kandidat inventarisiert, nicht portiert | Offen; Zielimport nicht geprüft |
| Jahressteuerbasis / WISO 2026 | Historische Kandidaten inventarisiert, nicht portiert | Offen; Zielinstallation/-import nicht neu geprüft |
| Allgemeine Outbox, Anhänge, Empfang | Historischer Kandidat inventarisiert, nicht portiert | Offen |
| WhatsApp / Post / Immobilienportale | Keine externe Aktion oder Veröffentlichung | Offen; kein Zustell-/Kauf-/Publikationsnachweis |
| Aktenwerk Receipt/Hash | Nicht bearbeitet | Offen |
| Notificationrouting / persönliche Receipts | Nicht bearbeitet | Offen |
| Neue Einstellungszentrale / Verbraucher | Nicht bearbeitet | Offen |
| Dokumenteditor / Annotationen / Originalschutz | Nicht bearbeitet | Werkzeugmatrix und Umsetzung offen |
| Verkauf / Eigentümerwechsel | Nicht bearbeitet | Offen |
| Messabdeckung / Bewohner / Widersprüche | Nicht bearbeitet | Offen |
| Mieterwechsel / Übergabenachweise | Nicht bearbeitet | Offen |
| Vertragsfristnachführung / Catch-up | Nicht bearbeitet | Offen |
| Projekte / Restmängel | Nicht bearbeitet | Offen |
| Müll-/ICS-/Ablesepläne / dauerhafte OCR-Jobs | Nicht bearbeitet | Offen |
| OCR → Rechnungsentwurf / Rechnungsoriginal | Nicht bearbeitet | Offen |
| Liquiditätsszenarien / gespeicherte Berichte | Nicht bearbeitet | Offen |
| Mieterportal / Offline / erweiterte Historie | Nicht bearbeitet | Offen |
| KI / S3 / Pluginupgrade / API-Fassade | Nicht bearbeitet | Offen |
| Portable vollständige Wiederherstellung | Nicht bearbeitet | Offen |
| Großbestände / Mehrbenutzer-Gesamtprüfung | Keine neue Vollmessung | Offen |

## Historische Kandidateninventur

Die Git-Arbeitskopien wurden gelistet, nicht pauschal fachlich übernommen: integration-history 0fb59785; integration-connections 552e3460; bank-import e01d3996; bank-discovery 80b548f7; teha-transport 951b3de5; teha-receive-domain b3d6d5d3; teha-transaction-unit-proposal 6d7157cb; datev-export d7ba1808; annual-tax-projection 12a537b3; annual-tax-fixture-guards ba12d451; buhl-probe 0ac0538b; communication-center d0a63ddf; portal-integrations-current 05f18c09. Eine Prüfung ihrer heutigen Daten-/Rechteverträge und Portierung ist noch erforderlich.

## Historische Integrationsanweisung für die ersten zwei Fixes

1. Zentralen Checkout erneut prüfen; ausschließlich gewünschte Commits übernehmen. Abhängigkeitsfolge: fe561d0a7cdbcdc4ee7b4adc1a23a1598450f5a7, danach ae44ab930fd1d1379ae546759d65d2ca47563cf2. Der nachfolgende Dokumentations-/Runnercommit enthält keine weitere Produktimplementierung.
2. Konfliktstellen: backend/auth.py, backend/routers/auth.py, backend/services/portfolio_http.py und backend/routers/messages.py. Bestehende spätere Änderungen nicht überschreiben.
3. Keine additive Migration oder neue Konfiguration für diese zwei Codecommits. Neue Fehlersemantik 503 und die interne Signatur revoke_token(..., require_unrevoked=True) bei Refresh berücksichtigen.
4. Aus einem eigenen Checkout mit frischen Datenpfaden prüfen: powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/run_pro_checks.ps1; anschließend gleicher Befehl mit -Backend sql. Der Runner setzt die isolierte Umgebung und protokolliert Commit, Tests und Exitcode. Für die erweiterte Prüfung -Tests mit test_auth_failclosed.py, test_message_thread_boundary.py, test_auth.py, test_upload_auth.py und test_portfolio_access.py verwenden.
5. Ruff/Mypy, verpflichtende vollständige Matrix und unabhängige PostgreSQL-/Browserprüfungen vor einer Freigabe erneut ausführen. Für die offene Frontendkorrektur die separat erhaltene Testspezifikation bewusst integrieren und alle sechs roten Fälle schließen; zusätzlich tatsächliche Browserfälle und Keyset-/Großthreadprüfung ergänzen.
6. Rückweg im Entwicklungs-/Integrationszweig: die beiden Codecommits in umgekehrter Reihenfolge regulär revertieren. Kein Schema-Downgrade erforderlich. Ein Revert stellt allerdings auch die früheren Fehlerpfade wieder her; keine automatische Empfehlung zur Produktivumstellung.

Aktuelle Ergänzung: Der eigene Zweig wurde bis b264cf81 regulär gepusht; CI-Lauf 38815280138 ist gestartet. Die neue Migration, die aktuelle Übernahmereihenfolge und neuen Prüfungen stehen in PRO_MESSAGE_WORKFLOW_20261016.md. Zusammenführung, unabhängige Freigabe, Release und Umstellung bleiben bei Codex.


## Fortsetzung 16.10.2026: gemeinsamer Verbindungsrahmen

Die obige Matrix kennzeichnet den historischen Stand bis zur Nachrichtenabnahme. Für den aktuellen
Verbindungsblock gilt ausschließlich `PRO_CONNECTION_SECURITY_ACCEPTANCE_20261016.md`.
Im eigenen Arbeitszweig wurde die private Connection-/Mapping-/Run-/Attempt-/
Receipt-Basis mit verschlüsselten Quellfeldern und dauerhaften, separat verifizierbaren
Ergebnisblöcken implementiert. Verlorene und verspätete Ausführungsergebnisse werden
getrennt mit expliziter Übernahme und ohne Neuversand behandelt. Ein Fehler bei der
Wiederherstellung des eingefrorenen Config-Snapshots wurde anhand vier ursprünglich
roter Archivefälle korrigiert.

Teststand dieses Teils: je 41/41 Memory und SQLite nach dem Fix, native 47/47
ohne Skip, zusätzliche native PostgreSQL-Vollsicherung samt frischer Zieldatenbank
1/1 ohne Skip, vollständige Memory-Backupmatrix 56/56, SQLite-Backupmatrix
57/57, jeweils >10.000 paginierte Events und 10.033 getrennte Runs
mit Memory/SQLite ohne Verlust, reale Verbindungsbrowserprüfung 7/7
mit visuell begutachteten 320/360/1440-Aufnahmen, Frontendkomponententest
8/8 sowie gezielte Migrations-/Manipulations-/Recoveryprüfungen.
Jeder Lauf besitzt seinen eigenen Runtimeordner und getrennte Hashmanifestdateien.
Die Werkzeuge meldeten lediglich vorhandene Bibliothekswarnungen, keinen
übersprungenen Pflichtfall in den genannten nativen Prüfungen.

`full_backup.py` verifiziert die privaten SQL-Ciphertexte jetzt zusätzlich
auf der aus dem Vollarchiv extrahierten und von der Anwendung unabhängigen
Testkopie vor der Wiederherstellung. Beschädigte Belege verhindern Publikation;
unterbrochene externe Writes bleiben nach Restore ausdrücklich `unknown`.
Die Migration `e160a1b2c300` folgt additiv auf `d73f2b9a041c`.
Der alte globale Konfigurationsweg bleibt bewusst eigenständig; ein ungetestetes
automatisches Umstellen aller Legacy-Geheimnisse wurde **nicht** behauptet.

Der übrige vollständige Handoverauftrag ist damit weiterhin offen.
14 getrennte `pro-finish-*-20261016`-Worktrees sind für die Pakete vorbereitet;
mehrere besitzen umfangreiche uncommittete Produktänderungen. Sie werden
nicht still oder konfliktüberschreibend als fertig integriert deklariert.
Ältere erfolgreiche Tests rechtfertigen keine Abnahme späterer Zusammenführungen.
