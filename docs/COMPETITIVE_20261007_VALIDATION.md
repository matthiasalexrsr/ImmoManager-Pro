# Wettbewerbsanalyse und Dokumentenabläufe – Abnahme vom 7. Oktober 2026

Arbeitszweig: `codex/party-document-workspace-20261007`, auf dem weiterentwickelten Claude-Stand. Diese Abnahme ergänzt die [vorherige Belastungsprüfung](HARDENING_20261007_VALIDATION.md). Sie gibt keine allgemeine Freigabe aller historischen A–L-Pakete oder externer Schnittstellen.

## Abgegrenzte Änderungen und unabhängiger Review

| Paket | Nachweis |
| --- | --- |
| Immobilien-/Einheitenakte | `9bc8b096`: aktive Einheiten- und Dokumentaktionen, korrekte Rückwege, Ladefehler mit Wiederholung, Schutz gegen verspätete Antworten. Unabhängig durch einen zweiten Astra-Ultra-Agenten geprüft. |
| Prüfliste und Buchung | `4af96bc0`: konkrete Buchung unabhängig von ihrer Listenposition laden, Beleg anzeigen, Rückweg zur Prüfung. Unabhängiger Review fand zwei P2-Fälle; `cc2ab83a` schützt wiedergeöffnete Bearbeitungsdialoge vor alten Speicherantworten und unterscheidet eine unbekannte Kategorie von einer fehlenden Zuordnung. |
| Kontakt-/Adresssuche | `892349b1`: tatsächliche Modellfelder und lesbare Kontaktbezeichnungen. 18 Regressionen zunächst fehlgeschlagen, nach der Korrektur in Memory- und SQL-Store bestanden; unabhängig geprüft. |
| PDF-Vorschau | Tatsächlich leere native Browseransicht mit gültiger Datei nachvollzogen. Striktes PDF-Parsing, HTTP 200/206, Poppler, PDFium und später PDF.js bestätigen eine gültige Quelle. Neue Darstellung lokal mit PDF.js; abschließender Paketnachweis folgt unten. |
| Dateizugriff | Separater [P1-Audit](FILE_ACCESS_AUDIT_20261007.md) bestätigte anonymen Upload-/OCR-Zugriff in normalem und Testversionsmodus. `198029b8` schützt statische Dateien mit aktiven Sitzungen; `094bf097` bereitet den geschützten Zugriff aus der Oberfläche vor und bestätigt Abmeldungen serverseitig. `2ff2cfe0` behebt die Typ-/Importprüfung ohne Laufzeitänderung. |

## Tests vor der ergänzten PDF-/Zugriffsänderung

- **157/157 Frontendtests**, 29 Dateien, ein Worker, unverändertes Standardtimeout. ESLint und Produktionsbuild erfolgreich. Parallel ausgeführte frühere Läufe hatten Zeitüberschreitungen in bestehenden Tests; sie werden nicht als bestanden gezählt.
- **34 fokussierte Backendtests** für Suche, Zahlungsaufteilung und Prüflinks erfolgreich. Die frühere gesamte Backend- und Großbestandsabnahme bleibt im oben verlinkten Bericht; sie wurde für die drei begrenzten Änderungen nicht pauschal wiederholt.
- **23/23 gezielte Buchungs-/Reviewtests** nach den beiden unabhängigen Korrekturen erfolgreich.

## Tatsächliche Browserabläufe

Die Prüfung verwendet eine isolierte Kopie der lokalen Testdaten mit eigener Datenbank, eigenen Uploads und separatem Loopback-Port 52195. Für Fehlerfälle wurden eine ausdrücklich synthetische QA-Buchung, ein Bildbeleg und drei PDF-Prüfdateien ergänzt. Keine Wettbewerberdatensätze oder eigentlichen Anwendungsdaten wurden verändert.

| Ablauf | Beobachtetes Ergebnis |
| --- | --- |
| Immobilie → Einheit → Partei → Rückweg | Richtige Akte und Partei erreichbar; Rückweg führt zur zugehörigen Immobilie. Desktop und schmale Ansicht kontrolliert. |
| Immobilie → Dokument | Dokumentaktion öffnet den gemeinsamen Betrachter; fehlende native PDF-Darstellung war der konkrete Auslöser für Paket 4. |
| Prüfliste → QA-Buchung → Bildbeleg → Prüfliste | Richtige Buchung hinter Position 7.000 geladen, obwohl die Tabelle nur die erste Seite zeigt. Tatsächliches PNG sichtbar; Enter öffnet, Escape schließt. |
| Unbekannte Buchungs-ID | Verständlicher Fehler und Wiederholung; keine Ersatzbuchung oder vorgetäuschter Leerbestand. |
| Globale Suche | Suche nach einem tatsächlichen Firmennamen findet den passenden Kontakt. |
| Mobile Akten/Belege | 320 und 360 Pixel, vollständige Aktionen, umgebrochene Dokumenttitel und kein seitlicher Überlauf der Gesamtseite; breite Datentabellen besitzen ihren eigenen Scrollbereich. |
| PDF.js im integrierten Browser | Echte drei Seiten mit Text, Umlauten und Farbfläche sichtbar. Direktsprung 1 → 3, zurück zu Seite 2, 200-Prozent-Zoom und Breitenanpassung funktionieren. PDF-Text zeigt den korrekten Inhalt der ausgewählten Seite. |
| PDF bei 320 Pixeln | Dialogbreite 305 Pixel, angepasste Canvasbreite 274 Pixel, Dokumentbreite 320 Pixel. Schaltflächen vollständig erreichbar, Seite visuell geprüft. |
| Beschädigte PDF | Eindeutiger Hinweis auf ungültige PDF; Wiederholung kehrt in denselben verständlichen Fehlerzustand zurück. |
| Passwortgeschützte PDF | Schutz wird erkannt; Hinweis auf Öffnen im PDF-Programm, kein endloser Ladezustand. Passworteingabe innerhalb des neuen Betrachters ist noch nicht implementiert. |

Der Download wurde in der Oberfläche ausgelöst. Die Browsersteuerung lieferte beim Warten auf ihr Download-Ereignis keine Abschlussmeldung; dies gilt nicht als nachgewiesener lokaler Dateidownload. Dateiauslieferung und Download-Helfer werden zusätzlich auf HTTP-/Testebene geprüft.

## Wettbewerberrecherche

- [vermieter1-Liveinventar](VERMIETER1_LIVE_20261007.md): erreichbare Formulare, Felder, Abläufe und tatsächlich beobachtete GET-Schnittstellen. Gesperrte Tarifmodule oder ohne Bestand unerreichbare Folgeschritte werden nicht als vollständig untersucht ausgegeben.
- [WISO-Liveinventar](WISO_LIVE_20261007.md): 15 Masken des geöffneten Hersteller-Musterfalls, einschließlich offener Posten, Abrechnung, Zähler und Miethistorie. Keine gespeicherten Änderungen oder externen Aktionen.
- [Wohnungsgeberbestätigung](WGB_CONSOLIDATION_20261007.md): exakte wiederverwendbare historische Umsetzung und notwendige Archiv-/Rechte-/Migrationsanpassungen. Frühere Testprotokolle sind keine heutige Integrationsabnahme.

## Ergänzte PDF- und Dateizugriffsprüfung

- PDF.js-Paket `ece7a12d`: 40 gezielte Tests beim Autor; unabhängige zehn Rendererprüfungen bestanden, alle 201 lokal ausgelieferten PDF-Ressourcen bytegleich zur Paketquelle. Keine externen Schrift-/Renderingabrufe erforderlich.
- Dateizugriff unabhängig mit **47/47 Memory- und 47/47 SQLite-Prüfungen** abgenommen. Die zusätzlichen Typ-/Importkorrekturen bestanden mypy für die drei betroffenen Module, Ruff und 14 direkte/HTTP-Regressionen.
- Tatsächlicher isolierter HTTP-Server: anonyme PDF-, HEAD-, Range-, OCR- und unbekannte Dateianfragen 401; autorisierte Originalbytes und Teilbereiche korrekt; ungültiger expliziter Bearer wird trotz gültigem Cookie abgelehnt. Ein Dateicookie allein authentifiziert keine API. Nach Abmeldung alte Cookies und Tokens abgelehnt. **100/100 parallele Range-Anfragen**, zehn Clients mit derselben Prüfsitzung, keine Fehler, p95 100,1 ms. Das ist kein zusätzlicher Test mit zehn unterschiedlichen Benutzern.
- Tatsächlicher Browser mit gemeinsamem PDF-/Sitzungsbuild: Anmeldung, geschützte dreiseitige PDF und serverseitig bestätigte Abmeldung bis zur Loginseite erfolgreich.
- `npm ci`, ESLint, Audit und Produktionsbuild: Exit 0, keine gemeldete Schwachstelle. Frontend-Gesamtlauf vor UI-Umbau: **196/197**; erster PDF-Test überschritt 5 Sekunden. Unveränderte Einzelgegenprobe bestand in 651 ms. Ein Wiederholungslauf wurde zur Vermeidung doppelter Gesamtprüfungen vor dem priorisierten UI-Umbau beendet. Dies wird ausdrücklich nicht als vollständiger grüner Lauf gewertet.
- Dateileseregel im aktuellen Claude-Bestand: alle aktiven angemeldeten Benutzer können lesen; objektbezogene Leserechte sind noch nicht vorhanden. Der Schutz behebt anonymen Zugriff, behauptet aber keine Objekttrennung.

## Priorisierte visuelle Überarbeitung

Auf erneute ausdrückliche Benutzerpriorisierung wurden Navigation, Dashboard und Listen gemäß [UI-Plan](UI_WORKSPACE_20261007_PLAN.md) gemeinsam überarbeitet. Unabhängiger Review, vollständige Frontendprüfung und tatsächliche Browserabnahme sind abgeschlossen.

Umgesetzte UI-Pakete:

| Paket | Umsetzung und fokussierte Prüfung |
| --- | --- |
| Navigation und gemeinsame Gestaltung | `8e518269`: dunkle kompakte Sidebar, sechs direkte Einstiege und alle 38 bisherigen Ziele in erreichbaren Gruppen, vollständiger Mobil-Drawer mit Fokusführung, gemeinsame Farben/Typografie/Formulare. Sechs gezielte Tests erfolgreich. Unabhängiger Review fand einen Dark-Hover-Kontrastfehler; vor Commit korrigiert, danach keine offenen P1/P2. |
| Immobilien, Parteien und Tabellen | `3472b390`: klare Akteneinträge, direkte Partei-/Mietkonto-/Dokumentaktionen, kompakte Bestandsleiste, Werkzeugleiste und Tastatursortierung. Zwölf gezielte Tests erfolgreich, einschließlich Export/Serverpaging und zweier im Review ergänzter Vertragsquellen-Gegenproben. Keine offenen P1/P2. |
| Dashboard | `346ccdd4`: vier kompakte Bestandsmetriken, priorisierte Vorgänge, Finanzüberblick, aufklappbare Fachbereiche und weiterhin sechs Analysen. Quellen mit eigenem Lade-/Fehler-/Wiederholzustand; keine Erfolgs-/Nullanzeige nach Ladefehler. 16 fokussierte Tests erfolgreich. Im unabhängigen Review irreführende Erledigt-Bezeichnungen in offenen Vorgängen korrigiert. |
| Seitenwechsel | `5d13615d`: bei anderem Pfad zum Seitenanfang; gleicher Pfad, Query und Hash behalten ihre Position. Browserbefund als Regression zunächst rot, danach sieben Shell-/Logoutprüfungen grün. |

**Tatsächliche UI-Abnahme auf der isolierten Datenkopie:**

- 1440 × 960: neues Dashboard, Immobilien- und Mieterlisten, sichtbare Tabellenhierarchie und Bearbeitungsformular. Immobilien sortieren per Enter; `aria-sort=ascending`. Desktopgruppen auf-/zuklappbar; Symbolnavigation besitzt verständliche Titel und öffnet beim Gruppenaufruf die vollständige Navigation.
- 320 × 800: Immobilienformular mit allen Pflichtfeldern und erreichbaren Abbrechen-/Speichern-Schaltflächen; volle Beschriftung im Drawer. Escape schließt ihn und fokussiert wieder „Navigation öffnen“. Partei-Infokarte, Dokumentregister und geschütztes Vertrags-PDF derselben Partei tatsächlich geöffnet. Dialoge und Seite ohne horizontalen Gesamtüberlauf.
- 390 × 844: dunkles Dashboard mit klar lesbaren Kennzahlen, Handlungsbedarf und Finanzübersicht; Seitenbreite und Scrollbreite identisch. 1024 × 900: dunkle Desktopnavigation, zweispaltige Hauptbereiche und erreichbare Navigation.
- Scrollkorrektur real geprüft: sichtbare Hauptüberschrift vor dem Seitenwechsel bei −872 px, nach Wechsel zur Mieterliste bei +130,8 px. Kein bloßer Test aus einer ohnehin oben stehenden Seite.
- Browserfehlerprotokoll nach den neuen UI-Abläufen leer. Keine Konkurrenzdaten verändert. Ein leeres Anlegenformular wurde ohne Datenerzeugung wieder geschlossen.
- Lokale Bildschirmnachweise: `artifacts/competitive-20261007/ui-dashboard-1440.jpg`, `ui-properties-1440.jpg`, `ui-tenants-1440.jpg`, `ui-navigation-320.jpg`, `ui-dashboard-dark-390.jpg`. Diese zeigen synthetische Testversionsdaten.

**Gemeinsame finale Prüfkette erfolgreich:** 218/218 Frontendtests in 39 Dateien mit einem Worker, Exit 0, 121,15 Sekunden. Keine Zeitüberschreitung. Ein vorheriger Lauf bestand 217/218; sein einziger Fehler war der veraltete Testselektor „Neu“ statt „Partei anlegen“. Nach dieser einzelnen Selektorkorrektur blieben alle fachlichen Cache-Erwartungen unverändert; die drei betroffenen Fälle und anschließend der gesamte Lauf bestanden. Vier nicht fatale jsdom-Hinweise zu nicht implementiertem `scrollTo` betreffen die Testumgebung; das tatsächliche Scrollverhalten wurde zusätzlich im Browser bestätigt.

ESLint, `npm audit` und Produktionsbuild jeweils Exit 0; Audit meldet keine Schwachstelle. Build 1,57 Sekunden, Hauptdatei `index-DYLkQOSY.js`, Dashboard `Dashboard-JavjWiFv.js`. Diese Ergebnisse beziehen sich auf den gemeinsamen UI-/PDF-/Sitzungsstand. Die frühere 196/197-Prüfung wird dadurch nicht rückwirkend als erfolgreich bezeichnet.

TEHA-Schreibvorgänge, WISO-Steuer-Zielimport, objektbezogene Leserechte sowie die weiteren Fachpakete bleiben eigenständige offene Arbeiten.

## Übergabe und aktualisierte Hauptvorschau

Auf ausdrücklichen Benutzerwunsch wird die weitere Entwicklung an Claude übergeben. Einstieg und konkrete nächste Integrationsschritte: [CLAUDE_HANDOFF_20261007.md](../CLAUDE_HANDOFF_20261007.md).

Die Hauptvorschau `http://127.0.0.1:8765/` wurde am 7. Oktober 2026 um 15:31 Uhr aus dem geprüften Stand `3f0d0421cb7baf53d749e19bdc20cef43705f527` neu gestartet. Die exakte Prozess-/Pfadidentität wurde vor dem Stoppen geprüft. Vorheriger SQLite-Bestand gesichert unter `../party-workspace-preview-20261007/backups/before-final-hardening-20261007-153136.db`; Anzahl von Parteien, Verträgen, Dokumenten, Buchungen und Benutzern unverändert. Alembic-Stand `d7a2f9c4e681`. Anmeldung, Bundleauslieferung sowie Aufgaben-/Integrationsabfragen erfolgreich.

Anschließend echte Browseranmeldung auf Port 8765 und neue Verwaltungsübersicht bestätigt; Browserfehlerliste leer. Der Browser bleibt auf der Hauptvorschau, der temporäre Viewport wurde zurückgesetzt. Die isolierte QA-Instanz auf 52195 wurde anhand ihrer Prozessidentität beendet, ihre Dateien für Reproduktion erhalten. Screenshot `artifacts/competitive-20261007/handoff-preview-8765.jpg`, maschinenlesbarer Startnachweis `artifacts/hardening-20261007/preview-final.json`.

Die Vorschau ist eine lokale Testversion. Das Update ersetzt keine Produktionsfreigabe oder installierte EXE. Die angelegte SQLite-Sicherung ist kein vollständiges Backup von Dateien, Konfiguration und Schlüsseln.
