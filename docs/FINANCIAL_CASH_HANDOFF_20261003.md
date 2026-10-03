# D1/D2 – gemeinsame Zahlungsquellen und historische Szenariokorrektur

Integrationsbasis `3b89187`; keine neue Tabelle, keine zweite Zahlungsbuchführung.
Diese Lieferung erfüllt einen abgegrenzten Teil von Paket D. Gesamtabnahme und
Auslieferung bleiben offen; laufende Vorschau weiterhin Release126.

## Tatsächlich umgesetzt

- `/api/v1/reports/cash`, `/sources`, `/export.csv`: derselbe gefilterte,
  berechtigte Buchungsbestand liefert centgenaue Dezimalstrings in EUR,
  Kostenarten, Monate und Objekt-/Einheitszuordnungen einschließlich Objektkosten
  ohne Einheit. Zeitraum, Portfolio, Immobilienauswahl, Einheit, Konto und
  Stichtag werden geprüft; widersprüchliche Zuordnungen ergeben einen konkreten
  Bearbeitungsfehler, keinen Leerbestand.
- Standard `confirmed_cash`: bestätigte Buchungen bis zum Stichtag.
  Unbestätigte, stornierte und zukünftige Quellen bleiben als ausgeschlossene
  Belege mit Grund sichtbar. `recorded_bookings` ist ausdrücklich der historische
  Buchungsbestand, keine Behauptung sämtlicher tatsächlich erfolgter Zahlungen.
  Noch nicht an Buchungen gebundene Zahlungsquittungen müssen im nachfolgenden
  Zahlungsklärungsablauf verbunden werden; sie werden hier nicht heimlich mit
  gezählt. Verknüpfte Bankbuchung und Zahlungsquittung zählen genau einmal.
- SQL liest konsistente, begrenzte Projektionen; Memory hält die gemeinsame
  Zahlungssperre. Gesamtbestand hat keine künstliche Grenze. Seitengröße und
  Transferpuffer begrenzen nur einen Arbeitsschritt. Cursor bindet Benutzer,
  Rechte, Filter, Seitengröße und Quellenhash. Veränderte Quellen verlangen
  Neuladen; Rechte und bereits gelesene Objektbezüge werden vor Veröffentlichung
  erneut geprüft, auch über eine unabhängige PostgreSQL-Verbindung.
- Vollständiger CSV-Export verwendet dieselben exakten Beträge und Ausschlüsse,
  begrenzte Puffer und geschützte Textzellen. Kein Export der sichtbaren Seite.
- Bestehende `/reports/finance` und `/cashflow` nutzen denselben Kern; alte
  numerische JSON-Felder bleiben für Aufrufer erhalten. Neue `exact*`-Felder,
  `currency`, `source_filters`, `source_hash` und exakt gefilterte `source_url`
  führen zu denselben Quellbelegen. CSV verwendet die exakten Felder.
- Historische Durchschnittsprognose: genau zwölf abgeschlossene Kalendermonate,
  einschließlich Null- und reiner Ausgabenmonate; eindeutiger Stichtag,
  keine zukünftigen/stornierten Buchungen, explizites Szenario-Anfangsguthaben
  oder gekennzeichnete Bestandsbasis ohne undatierte Kontoanfänge. Keine alte
  60-Monatsgrenze; 241 Monate tatsächlich geprüft. Zahlen werden intern exakt
  kumuliert und erst fachlich am Monatsausgang gerundet. Diese Prognose ist
  ausdrücklich noch keine vertragliche Forderungs-/Abschlagsprognose.

## Nachweise am zusammengesetzten Stand

- `test_financial_cash.py`:15 passed,85.85s, Memory/SQLite/HTTP. 10.001 Quellen,
  letzte CSV-Zeile, unveränderte Folgeseite, geänderte Quelle, Belegauswahl und
  Rechteentzug, 0.10+0.20, Kosten ohne Einheit, echter verknüpfter Zahlungsbeleg,
  zwölf vollständige Monate und 241-Monats-Szenario.
- Finanz-/bestehende Berichtsauswahl:26 passed,77.84s vor Ergänzung des
  zusätzlichen Zahlungsbelegtests; nach Ergänzung bleiben dieselben 26 Fälle
  grün und der neue Fall ist separat über beide Speichervarianten geprüft.
- Strikte PostgreSQL-Freigabeauswahl:4 passed,48.18s, **keine übersprungenen
  Fälle**. Vollständige 10.001 Quellen/CSV, exakte Objekt-/Einheitszahlen,
  verknüpfte Zahlung und unabhängige Quellverschiebung nach begonnener Abfrage.
- Ruff und mypy mit Python3.11-Ziel für vier produktive Finanzdateien geprüft.
  CI verlangt die PostgreSQL-Finanzfälle über den strikten Gate-Runner.

## Weiter erforderlich

Finanzarbeitsplatz und XLSX/visuell geprüfte PDF-Exporte, Vorperiodenvergleich,
Leistungszeiträume/Abschreibung/Finanzierung, vertragliche Prognose,
Budget-Istbelege, Kautionskonto, dauerhafte Mahnläufe, Rechnungspositionen.
100.000/1.000.000 echte Finanzzeilen mit Laufzeit-/Speicherprofil sind noch
auszuführen. Der heutige Quellenhash scannt den vollständigen Bestand und
prüft Bezüge nochmals; für umfangreiche interaktive Auswertungen werden
fortsetzbare, dauerhaft gespeicherte Berichtsläufe und gezielte Aggregate
benötigt. Vorhandene `Numeric(12,2)`-Quellspalten sind keine neue künstliche
Summengrenze, bleiben aber ein ausdrücklich zu migrierender Speicherpunkt.
