# Übergabe an Claude – ImmoManager Pro

Stand: **7. Oktober 2026, nach der gemeinsamen UI-, PDF- und Dateizugriffsprüfung**. Sprache und Produktziel: deutsche private Immobilienverwaltung mit mehreren Benutzern. Diese Datei ist der Einstieg für die Fortsetzung; die verlinkten Prüfberichte enthalten die ausführlichen Nachweise.

## 1. Auftrag und richtiger Ausgangspunkt

Der Benutzer übergibt die weitere Implementierung ausdrücklich an Claude, weil das Codex-Kontingent zur Neige geht. Die letzte Bitte lautet: „Mach ihm bitte eine detaillierte, sorgfältige Übergabe.“ Deshalb wurden keine weiteren Fachfeatures begonnen. Die angefangenen Agentenrecherchen wurden lesend abgeschlossen und unten eingearbeitet.

**Hier weiterarbeiten:**

```text
C:\Users\matth\Documents\Codex\2026-10-01\wi\work\party-document-workspace
Branch: codex/party-document-workspace-20261007
Geprüfter Produkt-/Teststand: 3f0d0421cb7baf53d749e19bdc20cef43705f527
Letzte funktionale Produktänderung: 5d13615da4e147140607d599bc39e64db2e401ca
Claude-Ausgangsstand: 3223a36a9d0e5db143b993b12a40ba72d5d376f2
Gemeinsames Git-Verzeichnis: C:\Users\matth\Documents\Codex\2026-10-01\wi\outputs\ImmoManager-Pro\.git
```

Der aktuelle Branch enthält Claudes genannten Ausgangsstand als Vorfahren. `3f0d0421` ändert ausschließlich einen Testselektor. Nachfolgende Übergabecommits enthalten Dokumentation und die Anpassung der CI-Node-Version, keine weitere Produktlogik. Den tatsächlichen Übergabe-HEAD mit `git log -1` feststellen; diese Datei kann ihren eigenen Commit nicht vorwegnehmen.

**Nicht in `outputs/ImmoManager-Pro`, einem alten Release-Worktree oder `root-correspondence-integration` weiterimplementieren.** Zahlreiche ältere Worktrees besitzen mehr historische Fachmodule, aber einen anderen Architektur-, Auth- und Migrationsstand. Kein pauschaler Merge/Reset auf deren HEAD. Vorhandene Änderungen anderer Bearbeiter erhalten. Die installierte Windows-EXE wurde durch diese Arbeiten nicht aktualisiert; die aktuelle Anwendung ist die unten beschriebene lokale Vorschau.

Benutzerprioritäten, weiterhin gültig:

- Von Claudes letztem Stand ausgehen; autonom sinnvoll weiterarbeiten und konkrete Fehler beheben.
- Moderne, elegante und praktisch brauchbare Oberfläche; bessere Partei-/Mieterakten mit Dokumenten und direkten Aktionen.
- Vollständige Fachabläufe statt bloßer Statusfelder oder Scheinaktionen.
- Privater lokaler Server mit Fernzugriff, mehreren Benutzern, großer Historie und möglichst geringem Wartungsbedarf.
- Keine stillen Gesamtbestandsgrenzen; begrenzte Seiten/Arbeitsschritte sind ausdrücklich sinnvoll, wenn vollständig fortsetzbar.
- WISO Steuer für Windows, erstes Zieljahr **2026**; TEHA aus Heppenheim mit vorhandenem Kundenportal.
- Individuelle Mieterwechselaufgaben, Müll-/Ablesepläne, Objekt-/Energieverträge, Projekte/Schäden/Handwerker, Finanzberichte und Wohnungsgeberbestätigung.
- Open-Source-Bibliotheken und vorhandene Implementierungen wiederverwenden. Externe Schreibvorgänge nur als abgenommen bezeichnen, wenn das Ergebnis tatsächlich bestätigt wurde.
- Zuletzt ausdrücklich **Astra Ultra** für Codex-Unteragenten. Dies ist eine übergebene Präferenz, keine Voraussetzung dafür, dass Claude ohne dieses Modell weiterarbeiten kann.

## 2. Sofortiger Einstieg für die nächste Sitzung

1. Dieses Dokument, [PARTY_WORKSPACE.md](PARTY_WORKSPACE.md), [aktuelle Abnahme](docs/COMPETITIVE_20261007_VALIDATION.md) und [WGB-Inventar](docs/WGB_CONSOLIDATION_20261007.md) lesen.
2. Im oben genannten Checkout `git status --short`, `git log -12 --oneline` und `git diff` prüfen. Übergabeänderungen sind bewusst separat gesichert; später hinzugekommene Nutzeränderungen nicht überschreiben.
3. Hauptvorschau `http://127.0.0.1:8765/` verwenden. Port **52195 war eine isolierte QA-Kopie und wurde bei der Übergabe beendet**.
4. Den nächsten kleinen, prüfbaren Integrationsschritt beginnen: **Originalarchivkern für die vorhandene Wohnungsgeberbestätigung**. Der genaue Portierungsplan steht in Abschnitt 8. Kein paralleler Neubau der schon vorhandenen WGB.
5. Danach vollständige serverseitige Suche/Auswertungen und dauerhafte Jobs bearbeiten; diese Codearbeiten wurden durch die UI-Priorisierung nicht erledigt und nicht vergessen.

## 3. Was seit Claudes Ausgangsstand wirklich umgesetzt wurde

### Parteiakten, Dokumente und Härtung

Die Parteiakte bis `eb458493` bietet kontextbezogene Informationen, konkrete Vertrags-/Mietkonto-/Dokumentaktionen und die Dokumenteneinsicht der ausgewählten Partei. Details und Datenzuordnung: [PARTY_WORKSPACE.md](PARTY_WORKSPACE.md). Darauf bauen alle folgenden Änderungen auf.

Die Härtung bis `bf57f5ee` ist in [Plan](docs/HARDENING_20261007_PLAN.md) und [Abnahme](docs/HARDENING_20261007_VALIDATION.md) dokumentiert:

- SQL-Datumsfilter vor der Paginierung statt stiller Vorabgrenze von 10.000 Zeilen; Index für Buchungen je Partei.
- Korrekte Cache-Lebensdauer, Schutz vor veralteten Ergebnissen, Abbruch wartender flüchtiger Jobs.
- Aufgabenserien, Erledigen/Wiederöffnen mit Konfliktprüfung und sichtbaren Ladefehlern; historische Vertragsparteien bleiben verfügbar.
- Dauerhaftes, seitenweise lesbares SQLite-Integrationsjournal ohne pauschale 200-Einträge-Grenze. Konfiguration atomar speichern; defekte Konfiguration nicht als leer behandeln.
- SMTP-Verbindungstest mit NOOP ohne Mailversand. Tatsächlicher Versand benötigt einen gewählten Empfänger; Fehler werden angezeigt.
- PostgreSQL-Migration `d7a2f9c4e681`: 39 frühere Float-Spalten in 17 Tabellen auf NUMERIC. Alle 46 im ORM deklarierten Dezimalfelder geprüft. **Das ist noch keine durchgängige Decimal-Umstellung sämtlicher Python-Berechnungen.**
- Wiederholbare isolierte Last-, Parallelitäts- und Wiederanlaufprüfungen, einschließlich echtem PostgreSQL.

### Wettbewerbsabgleich und konkrete Fachnavigation

| Commit | Fertiger Umfang |
| --- | --- |
| `9bc8b096` | Immobilien-/Einheitenakte: echte Detail- und Dokumentaktionen, korrekter Objektkontext/Rückweg, geplante Miete richtig beschriftet, verspätete Antworten und Ladefehler abgefangen. |
| `4af96bc0` | Prüfliste öffnet mit `?booking_id=` genau die betroffene Buchung, unabhängig von ihrer Listenposition; Beleg und Rückweg zur Prüfung. |
| `cc2ab83a` | Alte Speicherantwort schließt keinen neu geöffneten Buchungsdialog; unbekannte Kategorie wird nicht als fehlende Zuordnung ausgegeben. |
| `892349b1` | Globale Suche nutzt die tatsächlich vorhandenen Kontakt-/Adressfelder und korrekte Bezeichnungen. **Die globale Trefferbegrenzung und Speicherverarbeitung bleiben offen.** |
| `98cd457b` | Lesendes WISO-Liveinventar mit 15 geprüften Masken des Hersteller-Musterfalls. |

### PDF-Vorschau, Dateizugriff und Sitzungen

| Commit | Fertiger Umfang |
| --- | --- |
| `ece7a12d38eb8c484f59f399df33b653d00e4b5a` | Lokale PDF.js-Darstellung statt im integrierten Browser leerer nativer PDF-Einbettung. `pdfjs-dist` exakt `6.4.299`, Node mindestens 24. |
| `198029b8dfd64eebfae78047129904a32d04af9f` | P1 behoben: Uploads, OCR-Dateien, HEAD und Range waren zuvor anonym abrufbar. Jetzt aktive Sitzung vor der Dateisuche, auch im Testversionsmodus. |
| `094bf09734fe2481189956f16156893b1aa28ad4` | Frontend bereitet eigene geschützte Dateien sitzungsgebunden vor; Refresh-Singleflight und bestätigte Abmeldung, sichtbare Wiederholung bei temporären Fehlern. |
| `2ff2cfe02c182bfcbfcdf9f4d17f5f89f66190f1` | Eng begrenzte Typ-/Importkorrekturen, FastAPI-Injection erhalten; keine Laufzeitänderung. |

Details, die bei weiterer Arbeit erhalten bleiben müssen:

- `frontend/src/utils/uploadAccess.js`: nur gleichzeitig laufende Vorbereitung teilen, abhängig vom aktuellen Token. Kein dauerhaftes Erfolgscache, keine fremden signierten URLs mit eigener Sitzung versehen.
- `api.js`/Auth: genau ein Refresh je Tab; Logout wartet auf einen schon laufenden Refresh und widerruft auch dessen aktualisierte Sitzung. Bei Netzwerk-/5xx-Fehlern nicht einfach alle Zugangsdaten löschen und erfolgreiches Logout vortäuschen.
- Uploadcookie `immo_upload_access`: HttpOnly, host-only, Path `/uploads`, SameSite Strict, Secure bei HTTPS, gleiche Ablaufzeit wie Access-JWT. API akzeptiert diesen Dateicookie allein nicht als Anmeldung.
- Ein explizit ungültiger Bearer darf nicht auf einen gültigen Cookie zurückfallen. Deaktivierte Benutzer/widerrufene Sitzungen werden abgelehnt; Antworten private/no-store, Vary Cookie/Authorization und nosniff.
- Cookies sind host-, **nicht portgetrennt**. Produktion mit eigener HTTPS-Hostname-Grenze planen, nicht mit mehreren unterschiedlich vertrauten Diensten auf demselben Hostnamen.
- Die aktuelle Leseregel erlaubt allen aktiven angemeldeten Benutzern Lesen. **Objekt-/Portfoliorechte für Lesezugriff fehlen weiterhin.** Die Behebung anonymen Zugriffs ist keine Abnahme mandantenbezogener Isolation.
- PDF.js rendert die gewählte Seite, mit direkter Seitennummer, Text, Zoom 25–300 %, Breitenanpassung, Abbruch und Wiederholung. Canvasbudgets schützen Arbeitsspeicher; sie begrenzen nicht die Anzahl archivierter Dokumente oder PDF-Seiten.
- 201 Ressourcen für CMaps, Fonts, WASM und ICC werden anhand einer Allowlist lokal ausgeliefert, 3,53 MB insgesamt. `frontend/scripts/pdfjsAssets.mjs` und Vite-Integration erhalten; keine fremden CDN-/Schriftabrufe einführen.
- Verschlüsselte PDFs werden erkannt und können extern geöffnet werden. **Eine Passworteingabe im eingebauten Viewer ist noch nicht implementiert.**
- `source-map-js` wurde von 1.2.1 auf 1.2.2 aktualisiert; finaler npm-Audit meldete null Schwachstellen.

### Sichtbare UI-Überarbeitung – abgeschlossen, keine weitere Entwurfsphase nötig

| Commit | Änderung |
| --- | --- |
| `3472b390` | Immobilien-/Parteienlisten, Tabellen und Aktionen neu geordnet; Tastatursortierung mit `aria-sort`; Quelldatenfehler führen nicht zu falschen Nullwerten/„kein aktiver Vertrag“. |
| `8e5182699c1ad2e501823133914eb5df1efad081` | Dunkle kompakte Navigation, sechs direkte Einstiege und sechs Gruppen, alle 38 bisherigen Routen erreichbar. Mobiler Drawer mit Fokusführung, Escape, inertem Hintergrund und vollständigen Labels. |
| `346ccdd458291825f3575fc59291cec2cb5e5cfd` | Dashboard als Arbeitsübersicht: vier kompakte Kennzahlen, priorisierter Handlungsbedarf, Finanzen, Aufgaben/Fristen, fünf aufklappbare Fachbereiche, weiterhin sechs Analysen. |
| `5d13615da4e147140607d599bc39e64db2e401ca` | Seitenwechsel auf einen anderen Pfad scrollt an den Anfang. Gleicher Pfad, Query und Hash behalten ihre Position. |
| `3f0d0421cb7baf53d749e19bdc20cef43705f527` | Ausschließlich Testselektor `Neu` → `Partei anlegen` im Vertrags-/Parteicachetest; fachliche Erwartungen unverändert. |

Wichtige Dateien:

- `frontend/src/components/Layout.jsx`, `Shell.css`, **`frontend/src/index.css`**: tatsächlicher globaler Einstieg. Nicht versehentlich nur eine ungenutzte `styles.css` ändern.
- `components/DataTable.jsx`, `DataTable.css`, `pages/ListWorkspace.css`, `Properties.jsx`, `Tenants.jsx`.
- `pages/Dashboard.jsx`, `dashboard.css`, `components/DashboardWorkflow.jsx` und CSS.
- Neue Regressionen: `ListWorkspace.test.jsx`, `ShellNavigation.test.jsx`, `DashboardWorkspace.test.jsx`.

Gestaltung: petrolfarbene dunkle Sidebar, ruhige helle Flächen, lokaler Systemfont, eindeutige Hauptaktionen, konsistente Eingaben/Buttons, eigener Dark-Modus. Die vorhandene Gestaltung auf weitere Fachseiten übertragen. Keine neue UI-Bibliothek und keinen zweiten Designneubau parallel einführen. Bestehende Rollen, Parteienprovider, Tutorial, Sprache, Theme und vollständige Exporte erhalten.

## 4. Prüfstand: bestanden, historisch oder ausdrücklich offen

### Aktueller gemeinsamer Frontendstand

Nachweis: `artifacts/competitive-20261007/ui-final-verification.json` und zugehörige lokale Logs, zusammengefasst in [COMPETITIVE_20261007_VALIDATION.md](docs/COMPETITIVE_20261007_VALIDATION.md).

- **218/218 Tests, 39/39 Dateien**, ein Worker, Exit 0, 121,15 s. Kein erhöhtes Timeout und keine ausgelassenen Fälle.
- ESLint Exit 0; `npm audit` Exit 0, **0 Schwachstellen**; Produktionsbuild Exit 0, 1,57 s.
- Hauptasset `index-DYLkQOSY.js`, Dashboard `Dashboard-JavjWiFv.js`.
- Der erste UI-Gesamtlauf hatte 217/218: nur der alte Buttonselektor scheiterte. Nach der einzelnen Testkorrektur drei Gegenproben und der gesamte Lauf grün.
- Vier nicht fatale jsdom-Meldungen über nicht implementiertes `window.scrollTo` in bestehenden Tests. Der dedizierte Scrolltest und der tatsächliche Browserablauf sind geprüft. Diese Meldungen nicht mit Laufzeitfehlern verwechseln; bei künftiger Testpflege gezielt mocken, keine allgemeinen Fehlerunterdrückungen einbauen.
- Ein früherer Lauf vor der UI hatte 196/197 mit einem Timeout im ersten PDF-Test. Er ist dokumentiert und wird nicht rückwirkend als bestanden ausgegeben. Der neue vollständige Lauf ersetzt ihn als aktueller Frontendnachweis.
- Die drei UI-Pakete und Scrollkorrektur wurden unabhängig von einem zweiten Astra-Agenten geprüft; die gefundenen P2-Fälle sind korrigiert.

### Backend und Last: genaue Reichweite der Nachweise

Der letzte breite Backendlauf gehört zur Härtung bis `bf57f5ee`: **1.280 bestanden, 3 modusbedingt übersprungen**, zusätzlich **33 bestanden, 1 nicht anwendbar** im SQL-Sitzungslauf. Er enthielt echte PostgreSQL-Tests; erforderliche PG-Fälle wurden nicht als „skip = bestanden“ gewertet. Diesen alten Gesamtlauf nicht als Vollabnahme aller späteren Backendänderungen ausgeben.

Danach wurden die geänderten Bereiche gezielt geprüft:

- Suche/Zahlungszuordnung/Prüflinks: 34 Backendfälle; Suchkorrektur selbst 18 Memory-/SQL-Gegenbeispiele.
- Dateizugriff unabhängig: **47/47 Memory und 47/47 SQLite**. Typkorrekturen: mypy für drei betroffene Module, Ruff und 14 direkte/HTTP-Fälle.
- Isolierter echter HTTP-Server: anonyme PDF/HEAD/Range/OCR/unbekannte Datei 401; autorisierte Originalbytes 200 und Range 206; ungültiger Bearer trotz Cookie 401; Cookie allein an API 401; alte Sitzung nach Logout 401.
- Datei-Last: **100/100 Range-Anfragen, zehn Clients derselben Sitzung**, null Fehler, p95 100,1 ms. Das ist ausdrücklich kein zusätzlicher Zehn-Benutzer-Test.
- Frühere Million-Prüfung: 1.000.000 Buchungszeilen, 12.000 Dokumentmetadaten und 12.000 Aufgabenzeilen. Erste gefilterte Seite 0,033686 s, tiefe Offsetseite 1,205270 s, Worker-Spitze ca. 167,3 MiB. Geprüft wurden Seiten/Filter/Parallelreads, nicht sämtliche Analytics und kein physisches 12.000-PDF-Archiv.
- Früherer synthetischer Durchlauf: 4.405 gemessene API-Aufrufe, keine handlungsbedürftigen Befunde; zehn unabhängige Benutzer im Lastteil, 40/40 nachgelesene Schreibvorgänge.
- Echter PostgreSQL 16.15: zehn Benutzer, fünf Schreiber/fünf Leser, 200 gemischte Anfragen; 100 Buchungen und 100 Zuordnungen, beide exakt **1.111,00 EUR**. Details und Grenzen im Härtungsbericht.

### Tatsächlicher Browser

Die umfassende UI-Prüfung lief auf einer isolierten Datenkopie, nicht gegen die Hauptvorschau:

- 1440 × 960: Dashboard, Immobilien, Parteien, Sortierung per Enter, Desktopnavigation und Formulare.
- 320 × 800: vollständige Formulare/Buttons, Drawer/Escape/Fokusrückgabe, Parteiakte und Vertrags-PDF derselben Partei, kein horizontaler Gesamtüberlauf.
- 390 × 844 und 1024 × 900: Dark-Modus, erreichbare Navigation, lesbare Inhalte.
- Echte drei PDF-Seiten, Sprung 1 → 3 → 2, 200 % und Fit, lange Titel/Umlaute; beschädigte Datei mit Wiederholung; passwortgeschützte Datei mit ehrlichem Fallback.
- Reale Seitenwechselprüfung: alte Überschrift bei −872 px, neue bei +130,8 px. Browserfehlerprotokoll leer.
- Die Browser-Downloadschaltfläche wurde ausgelöst, aber das Automatisierungsereignis meldete keinen Abschluss. **Ein auf dem Rechner gespeicherter Download wurde damit nicht abschließend nachgewiesen.** HTTP-Bytes und Helfer sind separat geprüft.

Bildnachweise unter `artifacts/competitive-20261007/`: `ui-dashboard-1440.jpg`, `ui-properties-1440.jpg`, `ui-tenants-1440.jpg`, `ui-navigation-320.jpg`, `ui-dashboard-dark-390.jpg`. Alle zeigen synthetische Testdaten. Diese Artefakte sind lokal vorhanden, aber Git-ignoriert.

## 5. Laufende Anwendung, Daten und Sicherung

**Hauptvorschau nach erfolgreichem Update:** `http://127.0.0.1:8765/`.

```text
Runtime: C:\Users\matth\Documents\Codex\2026-10-01\wi\work\party-workspace-preview-20261007
Prozessmetadaten: <Runtime>\process.json
Start-PID laut Metadaten: 13036 (Python-Launcher; Listener kann dessen Kindprozess sein)
Listener bei Übergabe: PID 1104, verifiziertes Kind von PID 13036
Quellstand beim Start: 3f0d0421cb7baf53d749e19bdc20cef43705f527
Alembic: d7a2f9c4e681
Sicherung: <Runtime>\backups\before-final-hardening-20261007-153136.db
Startprotokoll: <Runtime>\logs\final-preview-20261007-153136.log
Prüfbericht: artifacts/hardening-20261007/preview-final.json
```

Die Vorschau wurde kontrolliert beendet, mit SQLite-Backup gesichert, explizit auf den bekannten Alembic-Head geprüft und neu gestartet. Anzahl von tenants/contracts/documents/bookings/users vor/nachher gleich. Anmeldung, Bundle und Tasks-/Integrationsabfragen bestanden. Anschließend tatsächliche Browseranmeldung und neue „Verwaltungsübersicht“ auf Port 8765 bestätigt, Browserfehlerliste leer. Das ist eine **lokale Testvorschau**, keine Produktionsserverfreigabe.

Der Browser wurde auf diese Hauptvorschau zurückgeführt, die temporäre Viewportvergrößerung zurückgesetzt und der Tab als Ergebnis geöffnet gelassen. Screenshot: `artifacts/competitive-20261007/handoff-preview-8765.jpg`.

Die separate QA-Instanz in `artifacts/competitive-20261007/browser-server` (Port 52195, vorher PID 28692) wurde nach Prüfung ihrer exakten Prozessidentität beendet. Ihre Metadaten tragen `status=stopped-for-claude-handoff`. Dateien und Datenbank bleiben zur Reproduktion erhalten. Darin liegen zusätzliche synthetische Testbuchungen/-PDFs; **nicht in die Hauptdatenbank übernehmen**.

Testkonto: Benutzer `mat.thias`, weitere Leserfixture `stb.hofmann`. Das gemeinsame reine Testpasswort ist im vorhandenen Code `backend/testversion/dataset.py`, Konstante `PASSWORD`, hinterlegt. Externe TEHA-Zugänge, JWTs und private `.env`-Werte absichtlich nicht in diese Übergabe kopiert. Die Runtime enthält eine bestehende private `.env`; nicht veröffentlichen oder neu generieren, wenn nur neu gestartet werden soll.

Sicheres vorhandenes Aktualisierungsskript: `artifacts/hardening-20261007/finalize_preview.py`. Es prüft PID, Pythonpfad, Port, Runtime und Arbeitsverzeichnis vor dem Stoppen. **Es ist auf Migration `d7a2f9c4e681` festgelegt**; nach neuen Migrationen bewusst anpassen. Keine Prozessbeendigung nach allgemeinem Namen `python`/`node`. Codex/Browser verwenden eigene Prozesse.

Die letzte Sicherung ist ein Datenbanksnapshot. Sie ersetzt nicht das noch offene Vollbackup von Uploads, Konfiguration und Schlüsseln oder eine regelmäßige isolierte Wiederherstellungsprobe.

## 6. Werkzeuge und reproduzierbare nächste Prüfungen

```text
Python mit eingerichteten Prüfbibliotheken:
C:\Users\matth\Documents\Codex\2026-10-01\wi\work\verification-venv-py312\Scripts\python.exe
Python: 3.12.15 (System-Python 3.14 nicht ungeprüft verwenden)
Node: C:\Program Files\nodejs\node.exe, 24.21.0
npm: 11.19.0
Ruff: 0.16.9; mypy: 2.3.1
```

PowerShell, getrennte Befehle im tatsächlichen Checkout:

```powershell
Set-Location 'C:\Users\matth\Documents\Codex\2026-10-01\wi\work\party-document-workspace'
git status --short
git log -12 --oneline
Set-Location .\frontend
npm ci
npm test -- --maxWorkers=1 --no-file-parallelism
npm run lint
npm audit
npm run build
```

Kein paralleler zweiter Gesamt-Vitestlauf, kein gleichzeitiger Lasttest und Browserbuild. Ein früherer Gesamtlauf zeigte einen PDF-Timeout; die Ursache wurde nicht abschließend bestimmt. Isolierter Gegenlauf und späterer serieller Gesamtlauf bestanden ohne Timeoutaufweichung. `npm ci` nur bei geänderten/fehlenden Dependencies erforderlich. CI nutzt nach der Übergabe dieselbe Node-Version 24.21.0; davor stand dort noch 20.19.0, unvereinbar mit der neuen PDF-Bibliothek. `frontend/README.md` wurde entsprechend aktualisiert. Die GitHub-CI wurde hier nicht remote ausgeführt.

Backendprüfungen müssen eigene Datenpfade, Uploads, Integrationskonfiguration und Testdatenbanken verwenden. Nicht einfach eine auf den Vorschaupfad zeigende Umgebung übernehmen. Vor einer neuen Prüfung `backend/tests/conftest.py`, aktuelle Testmarker und die vorhandenen Prüfscripte lesen. Für PostgreSQL echte eigene Testdatenbank/Verbindungen einschalten; ein Skip ist kein Parallelitätsnachweis. Für Änderungen an Archiv/Migration/Auth zusätzlich Memory, SQLite und PostgreSQL prüfen.

Wichtige lokale, teilweise ignorierte Hilfen/Nachweise:

- `artifacts/hardening-20261007/backend-final.log`/`.xml`, `sql-sessions-final.log`.
- `artifacts/hardening-20261007/postgres/`, `artifacts/audit-scale/measurements-after-hardening-1m.json`.
- `artifacts/competitive-20261007/ui-final-verification.json`, `ui-final-tests-after-selector-fix.log`, `ui-final-lint.log`, `ui-final-build.log`, `ui-final-audit.json`.
- `artifacts/competitive-20261007/file-access-runtime.json`, `check_file_access_runtime.py`.
- `artifacts/competitive-20261007/start_browser_qa.py`, `restart_browser_qa.py`, `seed_browser_case.py`, `set_browser_receipt.py`. Erst den Code lesen; Start erwartet teilweise eine neue Runtime, Restart prüft bestehende Identität.
- `scripts/party_workspace_browser_qa.mjs`, vorhandene Hardening-Browserharnesses sowie `.superpowers/sdd/COMPETITIVE_20261007/` mit Implementierungsnotizen.

Ignorierte Logs/Screenshots sind **kein Bestandteil eines frischen Git-Klons**. Die wesentlichen Ergebnisse stehen deshalb auch in versionierten Markdown-Berichten. Für Archivierung der ganzen Arbeitsumgebung lokale Artefakte gesondert erhalten, ohne Geheimnisse einzuchecken.

## 7. Was der Wettbewerbsabgleich ergibt

Lesen: [COMPETITIVE_REVIEW_20261007.md](docs/COMPETITIVE_REVIEW_20261007.md), [vermieter1-Liveinventar](docs/VERMIETER1_LIVE_20261007.md), [WISO-Liveinventar](docs/WISO_LIVE_20261007.md).

vermieter1 war im angemeldeten kostenlosen, nahezu leeren Konto zugänglich. Erreichbare Listen/Formulare, Objekt-/Einheiten-/Parteienbezüge, Zahlungen, Kosten, Zähler, Ablesungen, Abrechnung, Aufgaben, Dokumente und beobachtete GET-Schnittstellen wurden dokumentiert. Tarifgesperrte Funktionen lieferten teilweise 403; ein nicht erreichbarer Folgeablauf gilt nicht als untersucht. Keine Wettbewerberdatensätze erzeugt, keine Bankanbindung, Buchung oder kostenpflichtige Aktion ausgeführt. Keine Token-/Credentialdumps in den Dokumenten.

WISO Hausverwalter war nativ geöffnet. 15 Masken des Musterfalls wurden lesend geprüft; keine gespeicherten fachlichen Änderungen oder echten Übermittlungen. Besonders hilfreich: klare Objekt-/Vertragskontexte, offene Posten, Abrechnungsabläufe, Zähler-/Miethistorie und geführte Erfassung. Die wesentlichen Lücken unserer Anwendung liegen jetzt stärker in vollständigen Fachprozessen, Datenherkunft und verlässlicher Integration als in noch einer globalen Designrunde.

**WISO Steuer für Windows ist weiterhin nicht installiert.** Hausverwalter-Analyse und beobachtetes Exportformat sind kein eigener erfolgreicher Import. Zieljahr 2026 beibehalten, Profile je Jahr versionieren, Zielimport später tatsächlich prüfen.

TEHA-Kundenportal: `https://kunden.socs.ws`, Hersteller TEHA Heppenheim. Der Benutzer hat Zugang und die Analyse erlaubt. Historischer Lesetransport und Feldbeobachtungen existieren; aktuelles vollständiges Mapping/Übernahme/Schreibabnahme fehlt. Zugangsdaten aus der vorhandenen sicheren Nutzerkonfiguration beziehen, nicht aus dieser Datei. Ein unklarer externer Schreibausgang muss zuerst abgeglichen werden, nicht blind erneut gesendet werden.

## 8. Nächstes konkretes Paket: vorhandene Wohnungsgeberbestätigung portieren

Vollständiges Inventar: [WGB_CONSOLIDATION_20261007.md](docs/WGB_CONSOLIDATION_20261007.md). Die letzten beiden Astra-Agenten haben ausschließlich gelesen; **in der aktiven Anwendung wurde noch keine neue WGB-Datei oder Migration begonnen**.

### Bewährte Quelle und Wiederverwendung

```text
Vorhandener vollständiger Featurecommit:
f588c7fcba6adc7ff71200b6be072379b7f7e1ff

Gut lesbarer Quell-Worktree:
C:\Users\matth\Documents\Codex\2026-10-01\wi\work\release-readiness-a-l
HEAD: fc2cf695c512a25ea78102930799fa43ee02c23a

Alternative historische Integrationsquelle:
..\root-correspondence-integration
HEAD: 75ebd2fb76383705a27a12914e8b8000a47bbf43
```

Backend: `routers/housing_confirmations.py`, `services/housing_confirmation.py`, `housing_confirmation_types.py`, `housing_confirmation_validation.py`, `housing_confirmation_render.py`; NotoSans Regular/Bold und OFL unter `backend/assets/fonts/`.

Frontend: die sechs Dateien unter `frontend/src/features/housingConfirmation/`: `HousingConfirmationDialog.jsx`, `housingConfirmationApi.js`, `housingConfirmationModel.js`, `housingConfirmationText.js`, `useHousingConfirmationCommand.js`, `HousingConfirmation.css`.

Die historische Umsetzung kann bereits: manuelles tatsächliches Einzugsdatum, genaue Vertrag-/Objekt-/Einheit-/Parteiquellen, geordnete Bewohnernamen, Wohnungsgeber und gegebenenfalls anderer Eigentümer, echte PDF-Vorschau, drei ausdrückliche Bestätigungen, Quell-ETags und Reviewhash, unveränderliches Original mit Blöcken, Korrektur als neues Original, stabile Wiederholung nach verlorener Antwort und Cursorhistorie. Keine komplette Neuerfindung erforderlich.

### Schritt 1: interner Originalarchivkern und additive Migration

- Aus der alten Fassung `backend/db/document_version_models.py`, die erforderlichen DDL-/Unveränderlichkeitstrigger und Kernfunktionen aus `services/document_versions.py` / `document_version_validation.py` übernehmen.
- Neue Migration **hinter dem aktiven Head `d7a2f9c4e681`** schreiben. Der historische Dateiname `y1a2b3c4d5e6_document_versions.py` hat einen hier fehlenden Vorgänger. Nicht dessen ganze Vorgängerkette importieren. Die Archivtabellen referenzieren vorhandene Basistabellen und benötigen nicht automatisch alle alten Vorgangs-/Wizard-/Portfolio-DDL.
- Modelle für Anwendung/Alembic registrieren. Historischen hartcodierten Migrationsimport in `ensure_document_version_schema()` an die neue Struktur anpassen; regulären Start nicht unbemerkt zum Upgrade machen.
- Unveränderliche Manifest- und Chunkdaten, eindeutige `(document_id, number)` und `(actor, idempotency_key)`, richtige Beziehungen, Datenprüfung beim Lesen und verweigerter zerstörender Downgrade erhalten.
- Insbesondere `persist_version_bytes()`, Manifestprüfung und `verified_blocks()` wiederverwenden. Vorhandene gewöhnliche Uploads nicht nachträglich ohne Prüfung zu bestätigten Originalen erklären.
- Noch keine öffentliche Publikationsroute aktivieren, solange Transaktions-/Zugriffspfad und Wiederherstellung nicht korrekt sind.

Abnahme: leere/bestehende SQLite-Datenbank, echte PostgreSQL-Migration, Trigger gegen Update/Delete, fehlende/beschädigte/vertauschte Blöcke, Rollback nach teilweise geschriebenen Blöcken, sicherer Downgrade und Restoreprüfung. Historische `test_document_versions.py` und `test_document_version_recovery.py` gezielt adaptieren. Ein erfolgreicher SQLite-Dateibackup allein prüft die Archivsemantik nicht.

### Schritt 2: WGB-Fachmodul mit echten Transaktions- und Rechteadaptern

Verbindliche Risiken aus dem abschließenden Codeabgleich:

1. **Keine versteckte Commit-Grenze einführen.** Historisches `housing_confirmation.py` um Zeile 609 fügt `Document` bewusst innerhalb der eigenen Transaktion direkt ein. Die aktive `backend/repositories/document_repo.py:create_document()` committet sofort. Deren bequeme Wiederverwendung würde Dokument, Manifest und PDF-Blöcke trennen.
2. **Accountschutz bis zum tatsächlichen Commit portieren.** Der alte `tenant_privacy_fence.py` erwartet unter anderem `auth._user_store._lock` und für PostgreSQL `AuthSetupORM`. Der aktive `InMemoryUserStore` besitzt diesen Lock nicht. `getattr(..., None)` wäre ein stiller Ausfall des Schutzes. Sperr-/Revisionstechnik auf die wirklichen Accountschreibpfade abstimmen und das Rennen bis Commit prüfen.
3. **Aktuelle Grants für Vertrag und Dokument prüfen.** Die alten `scope_context`-/Portfolio-/`may_write_resource`-Modelle existieren hier nicht vollständig. Aktuelle `may_write(role, path)`- beziehungsweise Write-Grants explizit adaptieren. Keine angeblich vorhandene Objekt-ACL vortäuschen und keinen permissiven Rollenfallback einbauen.
4. Historische Wizard-Abfrage verwendet `ContractDraftORM`, auch wenn kein Entwurf ausgewählt ist. Hier entweder echte aktuelle Vorschlagsquelle adaptieren oder die optionale Wizardquelle ausdrücklich als nicht verfügbar behandeln; keine Abfrage einer nicht migrierten Tabelle zurücklassen.
5. Kleine ETag-/Cursor-/PrivateDownload-Verträge gezielt herauslösen. `document_versions.prepare_download()` hängt historisch an `scripts.private_server_backup`, `datev_export.CompiledExport`; der Router an `datev.PrivateDownloadResponse`. Dafür nicht das ganze DATEV-/Vorgangspaket ziehen und nicht auf öffentliche Uploadpfade ausweichen.
6. Korrektur erzeugt **neues Document plus neues Original** mit `correction_of`; altes Original bleibt bytegleich. Kein Überschreiben als generische Ersatzversion.
7. Actor+Idempotenzschlüssel, deterministische UUID sowie Request-/Review-/PDFhash erhalten. Wiederholung desselben Schlüssels muss das gespeicherte Original prüfen; abweichender Befehl unter demselben Schlüssel liefert Konflikt.

API-Präfix erhalten: `/contracts/{contract_id}/housing-confirmations` mit `GET /source`, `POST /preview`, `POST /preview-pdf`, Veröffentlichung am Präfix, Cursorhistorie und `GET /{document_id}/download`. Metadatenformat `housing-confirmation/1`, PDFformat `housing-confirmation-pdf/1`. Fachlicher Inhalt und Vorschauvertrag stehen vollständig im WGB-Inventar.

Abnahme vor Freischaltung: tatsächlicher Rechteentzug bis Commit, paralleler gleicher Schlüssel, verlorene Erfolgsantwort, veraltete Quelle, Korrektur, unverändertes früheres PDF, Dokumentlöschung/-umhängung, virtuelle Dateischatten, Wiederherstellung. Vorhandene Tests: `test_housing_confirmation.py`, `test_housing_confirmation_postgres.py`, `test_housing_confirmation_pdf_layout.py` und Archiv-/Privacy-/Recoverytests. Historische Erfolgszahlen sind keine Abnahme des neuen Ports.

### Schritt 3: vorhandenen Dialog in die heutigen Akten integrieren

- Einstieg in `frontend/src/pages/Contracts.jsx` an der konkreten Zeile mit `row.id`; zusätzlich in `features/partyWorkspace/PartyWorkspace.jsx` an jeder exakten Vertragskarte. Bei mehreren Verträgen keinen willkürlich auswählen.
- Auslöser für Fokusrückgabe behalten, Parteiakte während des zweiten Dialogs inert setzen. Alte `ContractLifecycle`-/`TenancyWorkflow`-Seiten sind dafür keine Voraussetzung.
- Die sechs vorhandenen WGB-Dateien übernehmen und an aktuelle `--color-*`-Variablen anpassen. Bewusste Vorschlagsübernahme, manuelles Einzugsdatum, Bestätigungen und eingefrorenen Wiederholungsbefehl erhalten.
- Aktuelles `api.js` besitzt noch keine `getBlob/postBlob`. Ergänzungen müssen Refresh-Singleflight, Logoutbarriere, Abort und Sitzungsprüfung **auch nach dem Bloblesen** erhalten. Nicht den heutigen API-Client durch den historischen ersetzen.
- Frontendrechte aus aktuellem `auth.write` für `/contracts` **und** `/documents`; beide Grants in die private Dialogbindung aufnehmen. Benutzer-/Vertrags-/Rechtewechsel verwirft private Wiederholungsdaten.
- Historische PDF-Neufenstervorschau würde das gerade behobene IAB-Problem wiederbringen. Vorhandenes `PdfPreview` mit verifizierten API-Bytes und eigens erzeugter/freigegebener Blob-URL verwenden, ohne die allgemeine URL-Freigabe von `FileViewer` aufzuweichen.
- **Gelesener Portierungsfehler:** `useHousingConfirmationCommand.js` um Zeile 28 setzt `mounted.current` im Effect-Cleanup auf false, aber im Setup nicht wieder auf true. Im heutigen StrictMode werden dadurch Ergebnisse verworfen. Beim Portieren korrigieren und mit StrictMode regressionsprüfen; bisher nur Codebefund, kein neuer Testlauf.
- Nach Veröffentlichung Dokumentcache und Parteiübersicht/-anzahl invalidieren. Typ `housing_confirmation` sinnvoll beschriften und Vertrag/Originaldownload korrekt zuordnen.

Prüfbasis: historische 20 Fälle in `HousingConfirmationModel.test.js`, `HousingConfirmationCommand.test.jsx`, `HousingConfirmationDialog.test.jsx`, `HousingConfirmationApiContract.test.js`; Einstiegstests und `frontend/e2e/housing-confirmation.pw.mjs`. Ergänzen: heutige Grants/Vertragskarten, StrictMode, authentifizierte Blobs, reale PDF.js-Anzeige, 320/360/1440 px, lange Namen/Adressen, mehrere Seiten, Korrektur und verlorene Erfolgsantwort.

## 9. Die verschobenen Codearbeiten und übrigen Lücken

Diese Punkte sind **nicht durch das fertige UI erledigt**. Vor Implementierung aktuelles Modell prüfen und die bekannten Altmodule inventarisieren.

| Priorität / Paket | Tatsächlicher Rest und nächste Abnahme |
| --- | --- |
| P0/P1 Zugriff | Objekt-/Portfolio-Leserechte fehlen im aktuellen Claude-Zweig. Einheitlich API, Suche, Kennzahlen, Dateien und indirekte Zuordnungen schützen; Rechteentzug/Mehrbenutzer bis Commit prüfen. Interne Leserrolle nicht als Mieterportal verwenden. |
| P1 B: Suche und vollständige Daten | Globale Suche lädt weiterhin Bestände und begrenzt auf zehn Treffer je Typ/50 gesamt ohne Folgeseiten. Stabile serverseitige Filter/Cursor, vollständige Kennzahlen und Exporte einführen. 100/101, 1.000/1.001 und >10.000 nachweisen. |
| P1 D: Finanzen | PostgreSQL-Datentypen sind korrigiert; Berechnungen und Berichte teilweise Float/Bestand im Speicher. Dezimalgenaue Quellbelege, Zeitraum/Portfolio/Immobilie/Einheit, Zahlungsübersicht vs. Periodenergebnis vs. Prognose, Nullmonate, Storno/Teilzahlung/Guthaben ohne Doppelzählung. |
| P1 E: Jobs/Betriebspläne | Allgemeine Jobs/Sperren teilweise prozesslokal. Dauerhaften fortsetzbaren Kern an Scheduler anschließen; mehr als 10.000 nachzuholende Vorkommen, Neustart, mehrere Worker, Sommerzeit/Regelversionen. Müllpläne/ICS-Ausnahmen/Ablesepläne mit Belegabschluss. |
| P1 I: Geheimnisse/Integrationen | Neues SQLite-Journal ist dauerhaft, Konfigurationsgeheimnisse aber noch unverschlüsselt. Alte verschlüsselte Journal-/Secretpakete prüfen, Schlüssel samt Vollbackup wiederherstellbar machen. Aktionen/Felder/Ergebnisstatus fachlich abnehmen. |
| P1 F: Einzug/WGB | Wie Abschnitt 8. Danach Übergabeprotokoll mit Räumen/Fotos/Mängeln/Schlüsseln/Zählern und vorhandene Mieterwechselvorlagen verbinden. |
| P1 G: Objekt-/Energieverträge | Anbieter/Kontakte, mehrere Vertragsorte, historische Tarife/Laufzeit/Preisbindung/Fristen; Erwartung/Rechnung/Zahlung getrennt. Auf vorhandenen Kontakten, Dokumenten und gemeinsamen Jobs aufbauen. |
| P1 H: Schäden/Projekte | Bestehenden Schaden zur Projektakte erweitern; Termine/Abhängigkeiten/Handwerker/Angebote/Aufträge/Nachträge/Rechnungen/Protokolle. Keine zweite konkurrierende Kostenbuchhaltung, keine zirkulären Abhängigkeiten. |
| P1 C: Verbrauch/Abrechnung | Aktueller Zweig enthält bereits eigene Usage-/Mietperiodenänderungen. Die alten Befunde nicht ungeprüft erneut als aktuellen Bug melden. Vollständige Regression für Medium+Maßeinheit, Zählerwechsel, datierte Bewohner, echte Abschnitte, Leerstand, Widerspruch und unveränderte finale Fassung durchführen; fehlende Teile ergänzen. |
| P1 I: TEHA | Zuordnung externer Objekte/Perioden/Einheiten, fortsetzbare Empfangsläufe, Änderungs-/Konfliktvorschau, bestätigter Dokumentimport, Techniktermine. Kosten-/Nutzerdaten und Restarbeitsaufträge erst einzeln mit realem Ergebnisnachweis freigeben. |
| P1 J: WISO 2026 | Isolierte Änderungsfälle aus Hausverwalter, versioniertes Mapping, Exportvorschau/Herstellerformat/Originalprotokoll. Echte WISO-Steuer-Installation fehlt für Zielimport und Wertevergleich. CSV/JSON nicht als bewiesene Herstellerkompatibilität ausgeben. |
| P1/P2 D/K: Finanz-/Kommunikationsabläufe | Kaution, Mahnung, Rechnungsprüfung, Widersprüche bis Beleg/Zahlung/Ergebnis verbinden. Kommunikationszentrum und echte Outbox wiederverwenden; lange Threads vollständig, falsche Antwortzuordnung verhindern. WhatsApp/INTERNETMARKE/Exposé nur mit tatsächlichem Nachweis. |
| P1 L: Betrieb | Explizites Upgrade von normalem Start trennen, keine versteckte Schemaänderung. Gesamtabhängigkeiten/Container reproduzierbar. Tägliche Vollbackups, zweites Ziel, Schlüssel/Anhänge/Konfiguration, monatliche isolierte Restoreprobe und Betriebsübersicht. |
| P2 Erweiterungen | Allgemeine Feldhistorie, dauerhafte Fachereignisse, Pluginmigrationen, Mieterportal mit mietvertragsgebundenen Berechtigungen, Finanzszenarien, gespeicherte Berichte, begrenzte Offlineentwürfe mit Konfliktprüfung. |

Das langfristige Ziel ist nachvollziehbare Wartbarkeit über 20 Jahre, keine garantierte Fehlerfreiheit oder wartungsfreie Laufzeit. Bereits gemessene Million-Pagination ist kein Nachweis für alle Berichte, Importe, Jobs und Restore auf dieser Größe.

## 10. Weitere historische Quellen, ohne pauschalen Integrationsauftrag

Alle folgenden Pfade relativ zu `C:\Users\matth\Documents\Codex\2026-10-01\wi\work`, sofern nicht anders angegeben. Vor Übernahme Branch/Status/Tests und Abhängigkeiten erneut lesen:

- `release-readiness-a-l` und `root-correspondence-integration`: umfangreicher alter Integrationsstand einschließlich WGB/Originalarchiv/Vertragsabläufen.
- `document-version-recovery`, `document-version-browser`, `portfolio-access`, `private-server-backup`, `restore-current`, `restore-session-security`: einzelne wiederverwendbare Grundlagen, aber ältere Auth-/Migrationsverträge.
- `teha-transport` (`951b3de512351dd9a2c782546628c08ff9eda102`), `teha-receive-domain` (`b3d6d5d382e656eb21c29726f0dc9ada917f4e6e`), `teha-transaction-unit-proposal`: historische TEHA-Arbeiten.
- `service-contract-g1-writer-plan`, `tenancy-workflow-core`, `tenancy-workflow-ui`, `contract-correspondence`, `contract-correspondence-calendar`: Fachpakete/Planungen mit gemeinsam genutzten Modellen; Versionsstand pro Paket klären.
- Kommunikationszentrum: `C:\Users\matth\Documents\Codex\2026-10-02\wi\work\communication-center`, HEAD bei Inventarisierung `d0a63ddfbc606a4eac669d74126c0039fe415ccc`.
- `claude_session_todo_analysis.md` im aktiven Repo: historische Anforderungen aus Claudes Sitzung; ein dort als „fertig“ beschriebenes Feature ist nicht automatisch im heutigen Integrationszweig freigegeben.

Der aktive Alembic-Zweig enthält eigene Billing-/Tenantdocument-/Mietperioden-/Zahlungszuordnungsänderungen und endet auf `d7a2f9c4e681` mit Vorgänger `8c4d2e6f1a93`. Alte Migrationen hängen an anderen Vorgängern. Neue konsistente additive Revisionen erstellen, gemeinsame Modell-/Rechte-/Recoverydateien zentral koordinieren.

## 11. Dokumentenkarte und Abschlusszustand

| Datei | Zweck |
| --- | --- |
| `PARTY_WORKSPACE.md` | Ausgang der aktuellen Partei-/Dokumentakten. |
| `docs/HARDENING_20261007_PLAN.md` / `...VALIDATION.md` | Umfang, breite Backend-/DB-/Lastprüfungen und ihre Grenzen. |
| `docs/POSTGRES_DECIMAL_MIGRATION_20261007.md` | PostgreSQL-Datentypkorrektur, Altbestand und Rückweg. |
| `docs/COMPETITIVE_20261007_PLAN.md` / `...VALIDATION.md` | Konkrete Wettbewerbs-/Datei-/UI-Pakete und aktuelle gemeinsame Abnahme. |
| `docs/COMPETITIVE_REVIEW_20261007.md` | Fachlicher Vergleich, Umsetzung und offene Prioritäten. |
| `docs/VERMIETER1_LIVE_20261007.md` / `docs/WISO_LIVE_20261007.md` | Tatsächlich beobachtete Konkurrenzoberflächen, erreichbare Felder und Grenzen. |
| `docs/FILE_ACCESS_AUDIT_20261007.md` | P1-Gegenbeispiel, behobener anonymer Zugriff und weiter fehlende Objektisolation. |
| `docs/UI_WORKSPACE_20261007_PLAN.md` | Abgeschlossene Gestaltung/Navigation/Dashboard/Listen. |
| `docs/WGB_CONSOLIDATION_20261007.md` | Detaillierte Feld-/API-/Datei-/Migrations-/Testinventur für die nächste Integration. |
| `frontend/README.md` / `CHANGELOG.md` | Aktuelle Entwicklungsbefehle und zusammengefasste Änderungen. |

Zur Übergabe laufen keine weiteren Agenten-Implementierungen oder Testläufe. Die drei zuletzt beteiligten Astra-Agenten haben Ergebnisse geliefert; ihr letzter zusätzlicher WGB-Abgleich ist in Abschnitt 8 eingearbeitet. Keine Nachrichten an externe Empfänger, keine TEHA-Schreibaktion und kein WISO-Steuer-Import wurden bei dieser Übergabe ausgeführt. Die breite A–L-Entwicklung ist **nicht abgeschlossen**; Claude soll sie vom gesicherten aktuellen Produktstand aus fortsetzen.
