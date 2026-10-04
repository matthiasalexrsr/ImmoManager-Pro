# Wartung und Schäden: vollständige Listenquelle und Oberfläche

Auf `ef82e18` (dort bereits behobener Datumsfilter-Deckel), eigener Branch
`assist/bounded-legacy-lists`, 2026-10-03.

## Ergebnis

Additive `/maintenance/inventory/page`, `/summary`, `/export` lesen dieselben
bestehenden `maintenance_cases`. Es gibt keine zweite Fall-/Projektdatenbank,
keine Migration und keine neue finanzielle Kostenableitung. Geschätzte Kosten
bleiben gespeicherte Planwerte. Bestehende CRUD-/Arrayrouten bleiben verfügbar.

SQL-Filter vor LIMIT: Suche in Titel/Kategorie/Zuständigkeit/Handwerker/Melder
und berechtigten Immobilien-/Einheitnamen; Status/Priorität/Kategorie, genaue
Immobilie/Einheit, Fälligkeits- und Termindatum. Prüfansichten überfällig,
hohe Priorität, ohne Termin, ohne Zuständigen. Überfälligkeit hat einen
expliziten Stichtag, den die Oberfläche mitsendet. NULLs zuletzt und ID als
stabiler Tiebreaker; Cursor binden Query und ActorScope. Die Projektion enthält
keine große Fallbeschreibung. Exaktes Nachladen vor Bearbeiten erhält diese
und die Originalrevision. Termine bleiben einschließlich Uhrzeit bearbeitbar.

Kennzahlen über die komplette gefilterte berechtigte Quelle, unabhängig von
der Seite. Gemeinsame Snapshot-/CSV-Implementierung jetzt aus den beiden
bewährten Units/Docs-Adaptern nach `inventory_export.py` extrahiert und für
alle drei Quellen erneut auf echtem PostgreSQL geprüft. Kleine Batches,
Formelschutz, erneute Scope-/Tokenprüfung und Vergleich mit aktuell berechtigter
Projektion vor Ausgabe. Kein browserseitiger Seitenexport. Browser-Blob bleibt
dateigroß; dauerhafte Exportaufträge sind weiterhin eine getrennte Folgepflicht.

Bewährter Document-Listenhook als eigenes `features/inventory/useInventory.js`
extrahiert; Documents und Wartung verwenden ihn, Units bleibt unverändert.
Bestehende ReferenceChoice/read/CSS bleiben in ihrem bisherigen Pfad und wurden
nicht verändert. Kein DataTable-/FormModal-/Layout-/Search-/Housing-/Billing-
Umbau. Immobilien-/Einheitenpicker lesen begrenzte berechtigte Referenzseiten.
Eigene Read-/Edit-Requests brechen bei Benutzer-/Scopewechsel ab; veraltete
Antworten und unpassende Detail-IDs werden verworfen. Fehler bleiben sichtbar,
Such- und Formulareingaben erhalten. Leser können filtern/exportieren, aber
keine schreibenden Aktionen auslösen.

## Nachweise

- Memory/SQLite Wartung + SQL-Exportkonkurrenz aller drei Quellen:
  **22 bestanden, 4 erwartete Memory-Skips**, 76,09 s. Positionen 101/1001/10001,
  vollständiger Export mit 10.025 Fällen, unabhängige Aggregate, NULL-/Datums-/
  Nullkostensortierung, explizite Stichtage/Terminbereiche, Scopeentzug,
  kein globaler Listenabruf/Autoflush, letzte HTTP-Veröffentlichungsprüfung.
- Tatsächliches PostgreSQL, gemeinsamer strikter Gate-Runner:
  **10 bestanden, null Skips**, 115,04 s. Wartung 4, Units 3, Documents 3;
  vollständige große Quellen und reale konkurrierende Writer während Export.
- Oberfläche: **37 bestanden in 4 Dateien**, 16,52 s (Wartung 11, Units 10,
  Documents 10, vorhandene OCR 6). Anschließender Wartungslauf nach präziser
  Beschriftung der Sortierauswahl: **11 bestanden**, 7,56 s.
- Echter Edge, frische synthetische SQLite-App: **2 bestanden**, 22,5 s,
  Wartung und Documents. 27 Fälle, Seiten 25+2, alle 27 CSV-Zeilen von Seite 2,
  exakter Detailabruf, 503-Speicherfehler mit erhaltenem Entwurf → erfolgreicher
  Retry, unveränderte Beschreibung/Nullkosten und geänderter Termin 16:45,
  neues Formular mit begrenzten Immobilien-/Einheitenpickern. Keine globalen
  Referenzlisten. Viewports 320/360/1440 ohne Seitenüberlauf; finale Desktop-
  und Mobilbilder visuell geprüft. Tabellen haben eigene horizontale Navigation.
- Produktionsbuild, scoped ESLint, Ruff, Mypy Ziel 3.11/3.12 erfolgreich.

Logs: `maintenance-inventory-backend.log`, `maintenance-inventory-pg.log`,
`maintenance-inventory-ui.log`, `maintenance-inventory-ui-final.log`,
`maintenance-inventory-e2e-final.log`. Der erste Browserlauf fand eine ungenaue
zugängliche Beschriftung der Sortierauswahl; explizite Feldnamen beheben sie,
der vollständige finale Browserlauf ist oben belegt.

## Folgeschritte

Kontakte haben noch einen kompletten RAM-Abruf vor Pagination, die Oberfläche
lädt nur die erste Seite. Mieter laden zwar über getAll vollständig, aber in
einen Browserbestand und ergänzen Verträge aus unvollständigen Referenzlisten.
Diese Fachadapter folgen einzeln unter Beibehaltung der Datenschutz- und
Lebenszyklusaktionen. Domain-Ownership vor Tenant-Privacy-Änderungen koordinieren.
Das spätere Projektpaket H soll auf diesen bestehenden Fall-IDs aufbauen.
