# Prüfung des integrierten Claude-Stands — 13. Oktober 2026

Status: Lokale Gesamtprüfung bestanden. Die gefundenen Probleme sind korrigiert; die endgültigen Ergebnisse und ihre Aussagegrenzen sind unten dokumentiert. Die Veröffentlichung erfolgt auf `codex/claude-review-20261013`; dieser Bericht behauptet keinen bereits erfolgreichen GitHub-Actions-Lauf.

## Geprüfter Ausgang und Arbeitsumfang

Ausgang ist `c3e1759d` auf `origin/claude/dreamy-gauss-nmaxhn`, einschließlich der früheren Codex-Übergabe `cbb1e04e`. Die Korrekturen liegen auf `codex/claude-review-20261013`. Der Ausgang wurde anhand der gemeinsamen Historie und der zusammengeführten Module ausgewählt; einzelne spätere Snapshotzweige sind kein neuerer vollständiger Integrationsstand.

Geprüft wurden insbesondere die neuen Fachmodule für Kautionen, Mahnwesen, Rechnungsprüfung, Dienstleistungsverträge und Projekte sowie Portfoliozugriff, Hintergrundarbeit, Vollsicherung, Schlüsselverwaltung und Dokumentabläufe. Drei Astra-Ultra-Assistenten bearbeiteten abgegrenzte Prüfbereiche. Die zentrale Integration hat ihre Änderungen gemeinsam geprüft.

Alle Datenbank- und Browserprüfungen verwenden eigene synthetische Daten. Die laufende Anwenderinstallation und ihre Daten wurden nicht migriert oder ersetzt. Externe Übermittlungen an TEHA, WISO, Banken oder Empfänger wurden nicht ausgeführt.

Der abschließend eingefrorene Produktstand ist `2034ea29`; spätere Änderungen dieses Prüfabschlusses betreffen ausschließlich diesen Bericht und das Changelog.

## Nachgewiesene und korrigierte Fehler

| Bereich | Fehler und Korrektur |
| --- | --- |
| Portfoliozugriff | Doppelte Authorization-Header konnten unterschiedliche Identitäten in Middleware und Route erzeugen. Beide verwenden dieselbe Header-/Cookieauswertung; Regressionen prüfen Listen, Dateien und Protokollzugriff. |
| Rechte bis zum Speichern | Implizites Flush und Core-UPDATE/DELETE konnten die abschließende Rechteprüfung umgehen. Schreibvorgänge werden vor dem Commit erfasst; eine abgelehnte Wiederholung behält ihre Sperre bis zum Rollback. |
| Vollsicherung | Das Entfernen des PostgreSQL-Passworts aus Werkzeugargumenten funktionierte mit `URL.set(password=None)` nicht. Das Passwort wird ausdrücklich entfernt und nur über die Prozessumgebung übergeben. |
| Schlüsselverwaltung | Gleichzeitige Erstellung oder Rotation konnte bestätigte Schlüssel eines anderen Workers verlieren. Betriebssystemweite Dateisperren und erneutes Lesen unter der Sperre serialisieren Änderungen. |
| Kautionsabrechnung | Eingereichte Positionskennungen konnten fremde Positionen überschreiben. Doppelte Kennungen werden abgelehnt; neue Positionen werden nur eingefügt, vorhandene fremde Kennungen führen zum Konflikt und Rollback. |
| Mahnwesen | Zukünftige Zahlungen und Stornos verfälschten Stichtage; veröffentlichte Kautionsverrechnungen fehlten in einzelnen Forderungen. Stichtagsbezogene Zahlungen und datierte Verrechnungen werden berücksichtigt; gleichzeitige Ereignisse behalten eine eindeutige Reihenfolge. |
| Zahlungszuordnung | Projekt- und Dienstleisterzahlungen konnten denselben Buchungsbetrag getrennt verbrauchen. Beide verwenden eine gemeinsame Kapazitätsberechnung und dieselbe Buchungssperre. Stornos, Teilstornos und Erstattungen wirken auf die tatsächlich gezahlten Beträge. |
| Verdeckte Mietzuordnung | Eine berechtigt sichtbare Buchung konnte trotz bestehender, für den Benutzer unsichtbarer Mietzuordnung als Dienstleisterzahlung angeboten und verwendet werden. Die globale Existenzprüfung schützt den Betrag, ohne fremde Vertragsdaten offenzulegen. |
| Projekt- und Rechnungsstände | Projektkosten und Dienstleisterrechnungen berücksichtigten verknüpfte Zahlungen nicht einheitlich. Die gemeinsame Berechnung und die Freigabeprüfung der Rechnungsprüfung gelten auch für diese Pfade. |
| Rechnungslisten | Fälligkeits- und Skontofilter verwendeten abweichende Näherungssummen. Sie nutzen jetzt denselben Saldo wie die Detailansicht, einschließlich Gutschriften und geklärter Streitfälle. |
| Dubletten | Nach 500 groben Kandidaten endete die Prüfung stillschweigend. Alle Kandidaten werden in begrenzten Arbeitspaketen geprüft; ein tatsächliches Duplikat hinter 501 unpassenden Kandidaten wird erkannt und abgelehnt. |
| Abrechnungskosten | PUT/PATCH erlaubten das Verschieben von Entwurfskosten in bereits bestätigte Perioden. Quelle und Ziel werden geprüft; PATCH prüft außerdem Herkunftsrechnung und das vollständige resultierende Datenmodell. Ungültige Pflichtfelder führen zu einem verständlichen Fehler. |
| Abrechnungsabschluss | Auf getrennten PostgreSQL-Verbindungen konnten neue Kosten gespeichert werden, während die alte Berechnung finalisiert wurde. Abschluss, Regenerierung, Änderungen und Kostenübernahmen verwenden eine gemeinsame Transaktion und Periodensperren. Auch das Verschieben von Abrechnungen in bestätigte Perioden wird abgelehnt. |
| Abrechnungsforderungen | Gleichzeitige Erzeugung konnte denselben Saldo mehrfach als Forderung buchen. Die Periodensperre schützt jetzt auch diesen Ablauf; ein Fehler während der Verarbeitung setzt alle betroffenen Datensätze zurück. |
| Mietrückzahlungen | Auch der direkte Rechnungszahlungsweg konnte bereits als Mietrückzahlung zugeordnetes Geld erneut verwenden. Kandidatenliste und Speicherung lehnen Mieterbuchungen und bestehende Mietzuordnungen ab. |
| Bearbeitungsstände | Bei stillstehender oder rückwärts laufender Uhr konnten neue Änderungen denselben Bearbeitungszeitpunkt erhalten und eine alte Eingabe erneut akzeptiert werden. SQL- und Memory-Speicher erhöhen die Änderungskennung nun zuverlässig über die bestehende Millisekundentoleranz hinaus; Erstellungszeitpunkte bleiben unverändert. |
| Gleichzeitige Bearbeitung | Zwei echte HTTP-Anfragen mit demselben ursprünglichen Bearbeitungsstand konnten auf unabhängigen PostgreSQL-Verbindungen beide erfolgreich speichern. Der akzeptierte Stand wird nun an die eigentliche Schreibstelle weitergegeben und dort atomar verglichen. Der spätere Schreibversuch erhält 409; im Memory-Speicher erfolgen Vergleich und Änderung unter derselben Sperre. |
| Projektoberfläche | Die Dokumentauswahl berechnete die nächste Seite anhand lokal gefilterter statt geladener Zeilen. Die Pagination verwendet nun den tatsächlichen Seitenumfang. |
| Wohnungsgeberbestätigung | Eine verspätete Vorschauantwort konnte nach einer Formularänderung den alten Freigabestand wiederherstellen. Änderungen verwerfen die bisherige Prüfung; überholte Antworten werden ignoriert. |
| Testzuverlässigkeit | SQLite-Testverbindungen wurden durch den Transaktionskontext nicht geschlossen und blockierten unter Windows das Entfernen der Fixture. Verbindungen werden ausdrücklich geschlossen; beide zulässigen Reihenfolgen von Sicherung und Wiederherstellungsprobe sind geprüft. |

## Prüfverfahren und Nachweise

Eigene Python-3.12-Umgebung aus `backend/requirements-dev.txt` mit `constraints.txt`; frische Frontendinstallation aus dem Lockfile. PostgreSQL 16.15 läuft ausschließlich auf Loopback mit eigener Clusterstruktur und eigenen kurzlebigen Testdatenbanken. Jeder PostgreSQL-Test muss tatsächlich ausgeführt werden: `scripts/check_postgres.py` verweigert fehlende Konfiguration, fehlende Ergebnisse und jeden übersprungenen Fall. Dieser Prüfblock ist jetzt Voraussetzung der GitHub-Freigabekette.

Die Ergebnisse des ersten Backenddurchlaufs wurden zur Fehlerdiagnose verwendet, nicht als erfolgreiche Abnahme. Er lief während der Integration von Korrekturen. Maßgeblich sind die abschließenden Läufe des zusammengeführten Stands.

| Prüfung | Ergebnis |
| --- | --- |
| Frontendtests | 332 bestanden, 58 Dateien; 325,70 Sekunden. Vier bekannte jsdom-Hinweise zu `scrollTo`, keine fehlgeschlagenen Tests. |
| Frontend-Lint und Produktionsbuild | Bestanden. |
| Frontend-Abhängigkeiten | `npm audit --audit-level=low`: keine bekannten Schwachstellen gemeldet. |
| Python-Abhängigkeiten | `pip-audit -r requirements.txt --strict --desc`: keine bekannten Schwachstellen gemeldet. Auditwerkzeug in separater Umgebung, Produktumgebung unverändert. |
| Stresstest-Werkzeug: Prozessisolation und Mischbetrieb | 21 Tests bestanden; 10,23 Sekunden. Dies ist eine Prüfung des Werkzeugs, kein neuer großer Lastlauf. |
| Backend Memory mit Coverage-Grenze 80 % | 1.757 bestanden, 67 umgebungsabhängig übersprungen, keine Fehler; 86,56 % Coverage, 1.146,49 Sekunden. |
| Backend SQLite mit Coverage-Grenze 80 % | 1.755 bestanden, 69 umgebungsabhängig übersprungen, keine Fehler; 86,04 % Coverage, 1.283,68 Sekunden. |
| Vollständiger PostgreSQL-Prüfblock ohne übersprungene Tests | 57 bestanden, keiner übersprungen; 315,30 Sekunden. 14 PostgreSQL-Testdateien und der separate dauerhafte-Job-Parallelitätstest. |
| Backend-Lint und Typprüfung des Gesamtstands | Ruff bestanden; mypy: 364 Quelldateien fehlerfrei, einschließlich des atomaren Bearbeitungsschutzes. |
| Browser mit synthetischen Parteien und Dokumenten | Auf `2034ea29` erneut 14 von 14 Abläufen bei 320/360/1440 Pixeln bestanden; keine JavaScript-, API- oder Bereinigungsfehler. 17 unterschiedliche Ansichten wurden im ersten Lauf vollständig, im letzten Lauf zusätzlich repräsentative neue Screenshots visuell geprüft. PDF-Canvas, Textauszug, bytegleicher Download, Uploads, Tastaturfokus, Filter/Pagination/Exporte und Nur-Lese-Rolle geprüft. Chromium 153.0.8010.12, Playwright 1.62.1. |

Der Abgleich der einzelnen JUnit-Fälle umfasst in beiden Gesamtläufen dieselben 1.824 Fälle. Zusammen mit dem verpflichtenden PostgreSQL-Lauf wurden alle 1.823 anwendbaren Fälle mindestens einmal erfolgreich ausgeführt. Die einzige grundsätzlich nicht anwendbare Variante ist `test_sql_workspace_queries_are_bounded[memory]`: Ein reiner Memory-Speicher führt keine SQL-Abfragen aus. Die zugehörige SQLite-Variante besteht. Alle übrigen in einem Gesamtlauf übersprungenen Fälle sind durch einen erfolgreichen Lauf in der passenden Umgebung abgedeckt.

Lokale maschinenlesbare Berichte und Logs liegen unter `artifacts/review-20261013/`, Frontendlogs unter `frontend/artifacts/review-20261013/`. Maßgeblich sind `memory-final.xml`, `sql-final.xml`, `postgres-final.xml` und ihr Abgleich `case-audit.json`. Diese Laufartefakte enthalten lokale Pfade und werden nicht als Produktdateien eingecheckt.

Reproduzierbare Prüfkommandos (aus dem Repository, mit frisch installierten gepinnten Entwicklungsabhängigkeiten):

```text
python -m pip install -r backend/requirements-dev.txt -c constraints.txt
python -m ruff check backend scripts/check_postgres.py
python -m mypy backend scripts/check_postgres.py
python -m pytest backend/tests -q -ra --tb=short --cov=backend --cov-report=term --cov-fail-under=80
python scripts/check_postgres.py
```

Den Backendlauf getrennt mit `TEST_STORE_BACKEND=memory` und `TEST_STORE_BACKEND=sql` ausführen. Jeweils ein neues, eigenes `DATA_DIR` mit untergeordneten `UPLOADS_DIR`/`BACKUP_DIR` verwenden, `DATABASE_URL` ungesetzt lassen und beide Scheduler deaktivieren (`JOB_SCHEDULER_ENABLED=false`, `BACKUP_SCHEDULE_ENABLED=false`). `SQLITE_PERSISTENT_STORE`/`ALLOW_INMEMORY_FALLBACK` passend auf `false`/`true` beziehungsweise `true`/`false` setzen. Die SQL-Testfixture erzeugt ihre eigene temporäre Datenbank. Für den separaten PostgreSQL-Lauf ausschließlich einen separaten Testserver über `IMMO_TEST_POSTGRES_ADMIN_URL` angeben und die passenden Werkzeuge über `PG_BIN_DIR` bereitstellen.

Im Frontendverzeichnis: `npm ci`, `npm test -- --maxWorkers=1 --no-file-parallelism`, `npm run lint`, `npm run build` und `npm audit --audit-level=low`. Der reale Browserlauf nutzt `scripts/party_workspace_browser_qa.mjs` mit den im Skript beschriebenen QA-Umgebungsvariablen und einer isolierten Testversion.

Browsernachbereitung: In jedem Lauf wurden alle 41 angelegten Testdatensätze erfolgreich entfernt. Im früheren Lauf überschritt das Schließen des Testbrowsers das 10-Sekunden-Zeitbudget; beim letzten Lauf trat dies nicht mehr auf. Die unabhängige Prozessprüfung bestätigte beendete Browser-/Serverprozesse und den wieder freien Testport. Der endgültige Nachweis liegt in `artifacts/review-20261013/browser-atomic-evidence.json`.

## Aussagegrenzen

API-Kompatibilität: Der atomare Bearbeitungsschutz verwendet den gültigen `updated_at`-Wert, den ein Client aus dem gelesenen Datensatz zurücksendet. Bestehende `/api/v1`-Aufrufer ohne gültigen Zeitstempel behalten ihr bisheriges Verhalten; dabei kann eine spätere Änderung eine frühere überschreiben. Eine verpflichtende Revision für sämtliche externen Altaufrufer würde eine gesonderte API-Umstellung benötigen. Die eigenen Revisions- und Wiederholungsschlüssel der neueren Fachabläufe bleiben bestehen.

Diese Prüfung belegt die beschriebenen Fach- und Integrationsfälle auf dem geprüften Stand. Sie ersetzt weder den tatsächlichen WISO-Steuer-2026-Import noch die Abnahme externer TEHA-Schreibvorgänge. Ein neuer Millionendatensatzlauf oder 20 Jahre wartungsfreier Betrieb werden daraus nicht abgeleitet. Frühere Lastmessungen bleiben mit ihrem jeweiligen damaligen Stand und ihrer Hardware gekennzeichnet. Der GitHub-Push ersetzt keine Aktualisierung der laufenden lokalen Vorschau.
