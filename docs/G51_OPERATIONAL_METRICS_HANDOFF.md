# G51: geschützte Betriebsmetriken

Quellen: `docs/HISTORICAL_FEATURE_MATRIX.md:G51`,
`CODEBASE_AUDIT_TODO.md:M4`, `claude_session_todo_analysis.md:Abschnitt 6`.
Vorhandene sichere Fehlerdiagnose und Request-ID-Protokolle bleiben erhalten.

## Produktvertrag

`GET /api/v1/admin/operational-metrics` verlangt eine frisch geprüfte Rolle
Eigentümer/Verwalter und Zugriff auf alle Portfolios. Anonyme Anfragen erhalten
401, andere Rollen und ausgewählte Portfolios 403. Berechtigungsentzug während
der DB-Prüfung verhindert die Veröffentlichung. Die Antwort ist privat und
nicht cachebar. Es gibt keinen öffentlichen Metrikmount.

Die Messung gilt ausdrücklich **für einen Prozess seit seinem Start**. Sie
überlebt weder einen Neustart noch einen Restore. Mehrere Worker werden nicht
aggregiert. Produktionsprofil mit einem Worker bleibt die geprüfte Empfehlung.
Die Daten sind kein vollständiges Auditjournal und keine Prometheus-/Tracing-
Integration oder externe Monitoringdienstleistung.

HTTP: feste 9 Bereiche × 8 Methoden × 5 Ergebnisse = 360 Speicherplätze mit
festen Laufzeitbuckets; keine Ereignisliste. Unbekannte Pfade teilen eine
Kategorie. Eingehende URLs/Queries/Namen/IDs/IPs/User-Agent/Headers werden nicht
als Label oder Ereignis gespeichert. Messung umfasst Antwortstream und
Requestabschluss; ein abgebrochener 200-Download wird als abgebrochen gezählt.
Exceptions ohne vorbereitete Antwort zählen als Serverfehler; der vorhandene
äußere Starlette-500-Handler liefert die eigentliche Fehlerantwort. Exceptions
nach bereits vollständig gesendeter Antwort bleiben zusätzlich im separaten
Exceptionzähler sichtbar. Non-HTTP-Protokolle werden nicht gemessen.

DB: echter `SELECT 1` gegen den tatsächlich aktiven SQL-Store-Bind. Verwendet
vorhandene Pool-/Driver-Timeouts, **keine zusätzliche harte Probe-Deadline**.
Fehlermeldungen/DSNs/Dateipfade/Parameter werden nicht veröffentlicht. Memory
heißt `not_configured`, `persistent=false` und wird nicht als angeschlossene
Datenbank ausgegeben. Flüchtiges SQLite ist dagegen eine erreichbare SQL-DB,
jedoch `persistent=false`; URL und tatsächlicher Main-DB-Dateiname werden intern
geprüft, ohne sie zu veröffentlichen. Erreichbarkeit bestätigt keine Migration, Integrität oder
erfolgreiche Sicherung. Bei Ausfall der zugleich für Auth verwendeten Datenbank
kann bereits die Anmeldung/Berechtigungsprüfung scheitern; die Statusroute
umgeht diese Authprüfung niemals.

Jobs: tatsächliche manuelle/automatische `operational_tick`-Läufe, Dauer und
Erfolg/Fehler erst nach Transaktionsabschluss. Kein erfundener Queuebestand;
SMTP-Outbox/OCR/Rent-Batch haben weiterhin ihre eigenen Journale. Das feste
Jobprotokoll erhält die existierende Request-ID bei manuellen Aufrufen und
enthält keine Business-/Tick-IDs oder Fehlerwerte. CPU-Zeit ist kumulative
Prozess-CPU, kein Auslastungsprozentsatz. Kein Host-/User-/Prozessname wird
veröffentlicht.

## Enge Integrationshooks

- `backend/app.py`: `OperationalMetricsMiddleware` als äußerste User-Middleware
  nach TrustedHost hinzufügen; vorhandene Scope/DB/RBAC/Reihenfolge beibehalten.
- `backend/routing.py`: eigenen Router neben Admin mit bestehender Admin-
  Abhängigkeit einhängen. Der Router schützt zusätzlich seinen eigenen Scope.
- `backend/services/operational_schedule.py`: genau `operational_tick` mit
  Messkontext **außerhalb** des Transaktionskontexts umgeben; keine Scheduler-
  Planung, Transaktions-/Buchungsregel oder Cash-/SMTP-Aktion verändern.
- UI separat: kleiner Abschnitt in Settings → System, manuelle Aktualisierung,
  feste übersetzte Kategorien und genaue Worker-/Memory-/Jobgrenzen. Alte grüne
  Ergebnisse verschwinden bei Ladefehler; Konto-/Rechtewechsel bricht ab.

Keine Migration, Abhängigkeit, CI- oder Recoveryänderung erforderlich.
Alle Prüfungen verwenden synthetische Installationen und Dateien.

## Ausgeführte Abnahme

- 81 Backendfälle im SQLite-Modus: eigene HTTP-/Memory-/SQLite-/Stream-
  Regressionen plus bestehende sichere Diagnostik und lokale operative Läufe.
  Neuer Folgefall vor Headerübertragung zusätzlich mit den übrigen HTTP-/
  Streamfehlern geprüft; darunter Memory und SQLite mit tatsächlichem 500.
- Ruff auf sechs betroffenen Backenddateien, Mypy auf fünf Produktdateien.
- Ganze Frontendsuite: 751/751 in 60 Dateien mit `--maxWorkers=2`.
  Der zweite Lauf mit Standardparallelität hatte zwei ältere Bankimport-
  Asynczeitfälle (Options-Lookup nach Ablauf des Testtimeouts). Dieselben neun
  Bankimportfälle bestanden fokussiert; Bankprodukt/Testassertions unverändert.
- Neue Oberfläche 24/24 Fälle: DE/EN/ES, 401/403/500, ungültige Antwort,
  echte DB-/Memory-Unterscheidung, Doppelklick, Rechteverlust, Unmount/Abort,
  tatsächlicher Einbau im Systemtab. Benutzerverwaltung fokussiert 34/34;
  deren bestehender isolierter Settings-Versionsfall mockt den neuen Abschnitt.
- Lint und Produktionsbuild erfolgreich.
- Echter Windows-Edge-Test auf frisch migrierter eigener SQLite-Installation:
  1/1, wirkliche APIzähler/401, manuelle Aktualisierung, 360/320 Pixel ohne
  Seitenüberlauf und seitliche Tastaturbewegung der lesbaren Tabelle. Mobile
  PNG wurde visuell geprüft, keine PDF-/Binär-/Tokenartefakte eingecheckt.
- Die erste enge Readonlyprüfung fand keine konkrete Scope- oder PII-Lücke.
  Die nachfolgende unabhängige G51-Abnahme reproduzierte zwei DB-Probe-Fehler:
  SQLite-Memory wurde als persistent ausgegeben; Connection-bound Sessions
  wurden fälschlich als nicht erreichbar gemeldet. Der Followup korrigiert
  beide und zeigt flüchtiges SQL mit ausdrücklicher Verlustwarnung.
- Connection-/Session-Transaktionen werden nur lesend wiederverwendet; weder
  deren Commit/Rollback noch ihr Close gehört dem Probe. Bei einer idle
  Connection wird ausschließlich eine eigene kurze Read-Transaktion beendet.
  Die vorhandene scoped-session Registry bleibt der maßgebliche Sessionkontext.
  Ein zweiter Checkout bei einer aktiven SQLite-Memory-Session könnte deren
  gemeinsame Driververbindung zurückrollen und wird deshalb vermieden.
- Neue reproduzierbare Backendfälle prüfen echte Memory-/URI-/Dateibinds,
  Connection-bound Sessions, Poolgröße eins, die erhaltene ursprüngliche
  Transaktion und Sentinel-Daten vor dem anschließenden caller-eigenen Rollback.
  Die UI-Followupfälle prüfen DE/EN/ES für flüchtiges SQL und einen Tag
  virtuellen Uhrablauf bei weiterhin gemountetem Panel:
  Focus/Visibility/Render lösen keinen Abruf aus, erst der Refreshknopf.
- Lokaler PostgreSQL-/Linux-Browserlauf wurde nicht behauptet; die bestehende
  CI bleibt Roots integrierte Abnahme.

## Unabhängiger Followup: tatsächlich ausgeführte Gates

- Ausgangsbefunde: zwei echte SQL-Proben rot, bestehende 28 Backendfälle grün.
- Final: 38/38 Backendfälle im SQL-Modus (28 bestehende + 10 neue), einschließlich
  echter vollständiger API-/Session-/Scopeintegration; Exit 0.
- 28/28 Frontendfälle (24 bestehende + 4 neue), scoped ESLint, Ruff und Mypy
  auf dem geänderten Service erfolgreich. Bestehende Schema-/Token-/Business-
  Transaktionsregeln bleiben unverändert.
- Echter Edge-Lauf gegen frisch migrierte isolierte SQLite-Datei: 1/1,
  Produktionsbuild, reale APIantworten/Zähler/401 und 360/320-Pixel-Abnahme
  einschließlich Tastatur-Tabellenscroll erfolgreich. Mobile PNG visuell geprüft.
