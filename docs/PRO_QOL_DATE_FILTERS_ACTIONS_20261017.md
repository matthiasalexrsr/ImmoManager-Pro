# ImmoManager Pro – QoL: lokale Datumsfilter und eindeutige Tabellenaktionen

Stand: 17. Oktober 2026, isolierter Entwicklungszweig `pro/full-handover-20261016`.

**Entwicklungscheckpoint, keine Produktivfreigabe.** Der zentrale Integrator-Checkout `claude-review-20261013` (HEAD `04021da5`), Anwenderinstallationen, externe Anbieter, Datenbanken und sämtliche offenen Backend-/Migrationsdateien wurden durch diesen UI-Checkpoint nicht verändert.

## Implementiert

1. **Ganztägige inklusive Datumsgrenzen in Tabellen:** Der bisherige lexikographische Vergleich gegen `YYYY-MM-DD` schloss z. B. `2026-10-17T23:40:00+02:00` bei Filter `Bis 2026-10-17` aus. `DataTable` normalisiert ISO-Zeitstempel über den lokalen Kalendertag, konsistent mit `formatDate()`. Reine `YYYY-MM-DD`-Kalendertage werden ohne Zeitzonenverschiebung übernommen. Ungültige und fehlende Datumswerte werden in aktiven Datumsbereichsfiltern nicht fälschlich als gültige Termine angezeigt. Relevante Oberflächen sind u. a. Besichtigungen, Instandhaltungstermine und Änderungshistorien.
2. **Doppelte Auswahlfilteroptionen:** Gespeicherte Werte wie Zahl `1` und Text `"1"` erhielten zuvor in einem `<select>` denselben React-Key und dieselbe Anzeige. Die Auswahlwerte werden nun vor der Deduplizierung in ihre tatsächliche HTML-String-Repräsentation normalisiert. Echte `0`- und `false`-Werte bleiben vorhanden und eindeutig.
3. **Tabellenaktionen barriereärmer:** Icon-Schaltflächen für Bearbeiten, Löschen und weitere Zeilenaktionen besitzen weiterhin die bisherigen, verständlichen Aktionsnamen. Eine `aria-description` ergänzt den konkreten Datensatz. Damit werden mit Screenreadern mehrere gleichnamige destruktive Aktionen unterscheidbar, ohne visuell versteckte Kopien des Tabelleninhalts einzufügen.
4. **Keine zusätzlichen unsichtbaren Duplikate:** Ein zunächst verwendeter, optisch verborgener Beschreibungs-`<span>` wurde beim vollständigen Frontend-Gate als Integrationsregression entlarvt: vorhandene Tests fanden denselben Tabelleninhalt doppelt. Die endgültige Fassung verwendet ausschließlich `aria-description`; alle zuvor durch diese Regression betroffenen Tabellen- und Seitenprüfungen wurden erneut grün.

## Reproduzierbare Tests

- Zunächst demonstrierten zwei neue Tests die bisherige Abweichung bei ISO-Zeitstempeln und doppelt dargestellten Auswahlwerten (2 rot vor Korrektur), danach alle 12 Filtertests grün.
- Der zusätzliche Screenreader-Test demonstrierte die vor der Korrektur fehlende Datensatzbeschreibung; die endgültige `aria-description`-Implementierung ist grün.
- Gezieltes Regressionsbündel `DataTableFiltersQol`, `DataTableSortExportQol`, `DataTableServerPaging`, `DataTableBulk`: **44/44** zunächst grün.
- Nach Beseitigung der erst in der Gesamtmatrix sichtbar gewordenen DOM-Duplikate: die neun vormals betroffenen Testdateien einzeln im Bündel wieder **65/65 grün**.
- **Vollständige Frontend-Regression auf den endgültigen Quellbytes:** `npm.cmd run test -- --maxWorkers=1 --no-file-parallelism` → **720 Tests bestanden, 109 Testdateien bestanden, 0 Fehler**, Prozess-Exit-Code 0.
- `npm.cmd run lint` und `npm.cmd run build` → beide Exit-Code 0; Vite 8.1.0 baute 734 Module. `git diff --check` → keine Whitespace-Fehler.
- Nicht-blockierende Testwarnungen sind weiterhin sichtbar, u. a. ältere React-`act(...)`-Hinweise, Listenschlüssel und jsdom `scrollTo`. Diese sind getrennte Folgearbeiten, keine verdeckte Gesamtfreigabe.

## Offene Abnahmen

Die vollständige Vitest-Matrix, ESLint und Vite-Build ersetzen weder einen unabhängigen Browser-/Screenreader-Test auf unterstützten Geräten noch den PostgreSQL-/Migrationstest, Live-Provider-Verträge oder eine formelle Integrations-/Releasefreigabe. **Nur die beiden geprüften Frontend-Quelldateien und dieses Dokument sind Teil des separaten UI-Commits.** Die fünf schon vor dieser Arbeit uncommittet vorliegenden Backend-Dateien bleiben ausgeschlossen.
