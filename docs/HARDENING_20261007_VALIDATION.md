# Stabilisierung und Belastungsprüfung vom 7. Oktober 2026

## Stand und Umfang

Weiterentwicklung auf dem vorhandenen Claude-Stand `3223a36a9d0e5db143b993b12a40ba72d5d376f2`, mit den bereits integrierten Partei- und Dokumentenakten bis `eb458493`. Arbeitszweig: `codex/party-document-workspace-20261007`. Dies ist die Abnahme der fünf Pakete aus [dem aktuellen Arbeitsplan](HARDENING_20261007_PLAN.md), keine Gesamtfreigabe sämtlicher historischer A–L-Anforderungen.

Die Fachänderungen liegen in `e36ecaeb`, `4cb6dfa7`, `737a71ac`, `d4282c4b`, `705248d9` und `fdd8dd9b`; `b6e7d076` korrigiert die schmale Integrationsansicht. Alembic-Zielstand: `d7a2f9c4e681`. Die unabhängige Prüfung der Pakete und Nachbesserungen erfolgte mit GPT-6 Astra Ultra. Die separate lokale Vorschau verwendet diesen Arbeitszweig; die installierte EXE wird dadurch nicht ersetzt.

## Umgesetzte Korrekturen und Bedienabläufe

- Datumsbereiche werden vor Paginierung in der Datenbank gefiltert. Die bisherige Vorabbegrenzung auf 10.000 Einträge entfällt für Buchungen, Verträge, Rechnungen, Instandhaltung und Aufgaben. Ein Index unterstützt Buchungen je Partei.
- Abfrage-Caches verfallen zuverlässig, behalten keine unbegrenzten Altbestände und veröffentlichen keine während einer Änderung erzeugten veralteten Ergebnisse. Abgebrochene, noch wartende Jobs führen ihre Aktion nicht aus; abgeschlossene flüchtige Jobresultate besitzen eine konfigurierbare Aufbewahrung.
- Aufgabenserien rechnen vom letzten erzeugten Vorkommen weiter. Ungültige Altregeln werden einzeln gemeldet. Änderungen prüfen Objekt-/Einheitsbezüge; Bearbeitung erhält die Serienzuordnung. Erledigen und Wiederöffnen verwenden den erwarteten Bearbeitungsstand; Konflikte bieten ausdrücklich erneutes Laden an. Ladefehler erscheinen als Fehler mit Wiederholung. Historische Verträge zeigen auch archivierte Parteien.
- Integrationen beschreiben und validieren Konfiguration und Aktionen. Maskierte Geheimnisse bleiben erhalten. Konfiguration wird atomar gespeichert; defekte Dateien werden weder still ersetzt noch als leere Konfiguration ausgegeben. Ein indiziertes SQLite-Journal speichert Vorgänge dauerhaft und seitenweise, ohne globale Eintragsgrenze. Unklare externe Ergebnisse bleiben erkennbar.
- SMTP verwendet die eingegebenen Verbindungsparameter. Die Verbindungsprüfung sendet keine Nachricht; bewusster Versand verlangt einen Empfänger und zeigt Ablehnungen als Fehler. Die Oberfläche bietet Konfiguration, Aktionen und vollständige blätterbare Historie, mit passenden Rollenrechten und korrigierter Darstellung ab 320 Pixeln.
- Eine zusätzliche PostgreSQL-Migration überführt 39 historisch als Float angelegte Spalten in 17 Tabellen in NUMERIC. Bereits dezimale Spalten bleiben erhalten. Die Prüfung erfasst alle 46 im ORM deklarierten Dezimalfelder. Details und Rückweg: [Migrationshinweise](POSTGRES_DECIMAL_MIGRATION_20261007.md).
- Der synthetische Stresstest verwendet eigene Datenverzeichnisse und kontrollierte Prozessgruppen. Windows-Unterprozesse erhalten die erforderliche Systemumgebung. Fehlgeschlagene Läufe behalten ihren Bericht und enden mit Fehlerstatus. Zehn getrennt angemeldete Benutzer prüfen tatsächlich überlappende Lese- und Schreibvorgänge einschließlich anschließender Inhaltskontrolle.

## Gemeinsame Prüfungen

| Prüfung | Ergebnis | Lokaler Nachweis |
| --- | --- | --- |
| Backend samt zusätzlichen Harness-Tests, reale PostgreSQL-Tests aktiviert | **1.280 bestanden, 3 übersprungen**, 10 Warnungen, 305,44 s | `artifacts/hardening-20261007/backend-final.log` und `.xml` |
| Ergänzende SQL-Sitzungs- und Parteiaktenprüfung | **33 bestanden, 1 übersprungen**, 11,01 s | `artifacts/hardening-20261007/sql-sessions-final.log` |
| Frontend | **123 bestanden** in 26 Dateien | `artifacts/hardening-20261007/frontend-final.log`; nach CSS-Korrektur nochmals bestanden |
| ESLint, Ruff für geänderte Python-Dateien, Frontend-Build | Bestanden | Lokale Ausgaben und Agentenprotokolle |
| Bestehende Partei-/Dokumentakten im echten Chromium | **14/14 bestanden**, keine Konsolen-, API- oder Aufräumfehler | `artifacts/party-browser/results.json` |
| Aufgaben und SMTP im echten Chromium | **11/11 bestanden**, keine Browserfehler | `artifacts/hardening-browser/results.json` |

Die drei Auslassungen des Hauptlaufs sind zwei SQL-Sitzungstests unter dem Memory-Store und ein dort nicht anwendbares SQL-Abfragebudget. Die beiden Sitzungstests wurden im ergänzenden SQL-Lauf ausgeführt; dessen eine Auslassung betrifft wiederum das Memory-Store-Abfragebudget. Keine erforderliche PostgreSQL-Prüfung wurde als übersprungen abgenommen. Die Warnungen betreffen bestehende Abkündigungen in Starlette/httpx, SQLite-Datetime-Adaptern und einem HTTP-Statusalias.

Die Browserprüfungen verwenden 320, 360 und 1.440 Pixel, echte Anmeldung, persistierte Aufgabenaktionen, PDF-/Bildvorschauen, Uploads, Dokumentfilter und Leserrechte. Der SMTP-Test verwendet ausschließlich einen eigenen lokalen TCP-Testserver: Verbindungstest mit NOOP und **null Nachrichten**, danach bewusster Versand an den gewählten Testempfänger samt Journaleintrag. Es wurde keine Testmail an einen externen Empfänger geschickt. Die finale Ansicht wurde zusätzlich visuell kontrolliert; Dokument- und Kartenbreiten passen ohne horizontales Abschneiden.

Nach dem letzten vollständigen Backend-Lauf wurden nur Importformatierung, der Browser-Prüfhelfer, Dokumentation und die isolierte CSS-Korrektur geändert. Python-Syntax/Ruff sowie Frontendtests, Build und Browserprüfung decken diese abschließenden Änderungen ab.

## Belastung und Mehrbenutzerbetrieb

Referenzrechner: Windows 11, Intel Core i5-10300H (4 Kerne / 8 logische Prozessoren), 23,77 GiB RAM, Python 3.12.15, SQLite 3.53.1. Messungen auf einem lokalen Rechner sind keine allgemeine Kapazitätszusage.

### Eine Million Buchungen

Fixture: **1.000.000 Buchungszeilen, 12.000 Dokument-Metadatensätze und 12.000 persistierte Aufgaben**. Die Dokumentzeilen sind kein entsprechendes Archiv physischer PDF-Dateien; Aufgabenzeilen sind keine Verarbeitung von 12.000 Hintergrundjobs.

- 990.000 Datumsfilter-Treffer; erste 200 und letzte zehn Treffer anhand ihrer erwarteten IDs geprüft.
- Erste gefilterte Seite: **0,033686 s**. Späte gefilterte Seite bei Offset 989.990: **1,205270 s**. Ungefilterte letzte zehn Zeilen: **0,249788 s**.
- Zehn unabhängige gleichzeitige Lesezugriffe: alle erfolgreich und inhaltlich vollständig, gesamte Gruppe **0,747032 s**, Median **0,365566 s**, höchster Einzelwert **0,4235 s**.
- Spitzen-Arbeitsspeicher des eigentlichen App-Workers: **175.468.544 Bytes (ca. 167,3 MiB)**. Der Launcher ist getrennt erfasst. Der Abfrageplan verwendet `idx_bookings_tenant`.

Nachweis: `artifacts/audit-scale/measurements-after-hardening-1m.json`. Die Messung entstand während der Entwicklung; der dort als uncommittet gekennzeichnete Produktcode wurde anschließend in `4cb6dfa7` gesichert. Sie prüft gezielt paginierte Datenzugriffe, keine vollständige Million-Zeilen-Auswertung, Suche oder Wiederherstellung.

### Synthetische Verwaltung mit Fehler- und Wiederanlaufpfaden

Der endgültige, unveränderte Test-Harness verarbeitete **4.405 zeitlich gemessene API-Aufrufe** über 15 Einheiten und ein simuliertes Jahr in rund 5,3 Minuten: **null handlungsbedürftige Befunde**, fünf Hinweise. Enthalten sind Rollenprüfungen, ungültige Eingaben, Export/Import, Sicherung/Wiederherstellung, Neustart und Prozessabbruch.

Der Lastabschnitt mit zehn verschiedenen Benutzern (acht Leser, zwei Schreiber) erreichte **2.717 Anfragen in 30,10 s**, **40/40 nachgelesene Schreibvorgänge**, 142 beobachtete Überschneidungen, null HTTP-Fehler und **p95 0,2408 s**. Nachweis: `artifacts/hardening-20261007/runtime-verified/run-rwp_6c44/report.md`. Unter Windows beendet der Harness seine Prozessgruppe kontrolliert; dies wird nicht als geordneter ASGI-Shutdown bezeichnet.

### Echter PostgreSQL-Server

PostgreSQL **16.15**, eigene lokale Testinstanz, getrennte Verbindungen und zehn verschiedene authentifizierte Benutzer. Fünf Schreiber und fünf Leser führten **200 gemischte Anfragen** aus: erwartete Erfolgsantworten, Leser-Schreibversuch korrekt mit 403 abgelehnt. Gesamtzeit **4,410 s**, p95 **0,372972 s**.

Die unabhängige SQL-Prüfung bestätigt **100 eindeutige Buchungen und 100 Zahlungszuordnungen**, jeweils mit exakter Summe **1.111,00 EUR**. Kein bestätigter Vorgang fehlt oder wurde doppelt zugeordnet. Vollständige gefilterte API-Ergebnisse, aktualisierte Summen und Buchungsindex sind geprüft. Der zuerst gefundene Float-Fehler ergab zuvor 1111,0000000000002; die Nachprüfung einer bestehenden Datenbank erhält alle 100 ursprünglichen Zeilen und liefert nach Upgrade ebenfalls exakt 1111,00.

Nachweise: `artifacts/hardening-20261007/postgres/api-122218/results.json`, `postgres/upgrade-existing-result.json` sowie die aktivierten Migrationstests für Neuinstallation, Altwerte, große/kleine Werte, vorhandene Numeric-Typen und erneutes Upgrade.

## Verbleibende Grenzen und nächste Arbeit

- Vollständige Finanzberichte, globale Suche und einige Start-/Aggregationspfade laden weiterhin große Bestände in den Speicher. Die Million-Zeilen-Messung ist keine Freigabe dieser Pfade. Die frühere 100.000-Zeilen-Diagnose zeigte hier weiteren Optimierungsbedarf.
- Die PostgreSQL-Speicherung ist korrigiert; ORM-/Python-Finanzberechnungen verwenden teilweise weiterhin Float. Eine vollständige Decimal-Umstellung ist ein separates Fachpaket.
- Integrationsgeheimnisse sind beim Speichern noch unverschlüsselt. Konfigurationsänderungen und Serienerzeugung sind nur innerhalb eines Prozesses gegen konkurrierende Ausführung geschützt. Mehrprozessbetrieb benötigt darüber hinaus Datenbanksperren beziehungsweise eindeutige Vorgangsidentitäten.
- Das Integrationsjournal ist dauerhaft; die allgemeine In-Memory-Jobqueue ist dadurch noch kein dauerhafter, fortsetzbarer Scheduler. Zeitbegrenzte flüchtige Jobresultate sind ausdrücklich von fachlichen Historien zu unterscheiden.
- TEHA-Schreibabläufe und WISO-Steuer-Zielimport sind mit diesen lokalen Tests nicht abgenommen oder zusätzlich implementiert. Die fehlende Zielinstallation für WISO bleibt eine Voraussetzung des echten Importtests.
- Die Gesamtanforderungen an 20 Jahre Betrieb, Vollbackupautomation und alle Fachmodule bleiben weiterzuführen. Diese Abnahme liefert konkrete Regressionen, Lastmessungen und einen wiederholbaren Prüflauf statt einer Garantie für Fehlerfreiheit.

Temporäre Testdaten und Berichte bleiben zur Reproduktion erhalten. Die Testdienste werden nach der Prüfung beendet; die lokale Vorschau wird mit bestehendem Datenbestand und bestehenden Zugangsdaten aktualisiert.
