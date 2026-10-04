# P0: verlässliche Einheitenakte

Basis: Root `679c8de`, eigener Branch `assist/p0-unit-workspace`.

## Entscheidung vor der Umsetzung

Die alte Detailseite liest nur die ersten 100 globalen Verträge, benutzt falsche
Mietfeldnamen und veröffentlicht verspätete Antworten ohne Quellenbindung.
Der vorhandene Vertragsworkspace kann bereits nach `unit_id` und `property_id`
in SQL filtern, Mieternamen einbinden und signierte Cursorseiten liefern. Dieser
Kern wird wiederverwendet; keine zweite Vertragsabfrage und kein `getAll`.

`GET /units/{unit_id}/workspace` liefert die exakte berechtigte Einheit, eine
kleine Immobilienprojektion sowie getrennte Seiten für aktive Verträge,
Vertragshistorie und einheitsspezifische Versicherungen. Queryparameter sind
`page_size` (Standard 25, bestehendes konfiguriertes Vertragsseitenbudget),
`active_cursor`, `history_cursor`, `insurance_cursor`. Verträge sortieren nach
Beginn absteigend und stabiler ID. Versicherungen verwenden den vorhandenen
signierten Referenzcursor mit Bindung an Einheit, Immobilie, Seitengröße und
Benutzerrechte. Alle Filter wirken vor dem Limit; Memory hält nur eine Seite
plus Fortsetzungsindikator, SQL verwendet begrenzte SELECTs ohne Autoflush.

Mehrere aktive Verträge werden sichtbar aufgelistet, nicht willkürlich zu einem
einzigen Mieter verdichtet. Aktiv bedeutet explizit den gespeicherten Status,
nicht eine erfundene Belegungsberechnung. Die Historie bleibt unabhängig
blätterbar. Die Ansichten sind aktuelle Leseseiten, kein eingefrorener Export.
Keine Migration und keine Veränderung des bestehenden Vertragsworkspace-DTOs.

Die Oberfläche verwendet `cold_rent`, `service_charge_advance` und
`heating_advance`; 0 ist ein Wert, nur fehlende Angaben erscheinen als Strich.
Die Komponentenidentität bindet Einheit, Benutzer und Portfolio-/Schreibrechte;
Änderungen verwerfen alte private Inhalte schon beim Rendern. Requests werden
abgebrochen und zusätzlich vor Ergebnisübernahme geprüft. Ladefehler bleiben
sichtbar und bieten erneutes Laden; sie werden nicht als Leerstand ausgegeben.
Paginierung besitzt getrennte Vor-/Zurück-Steuerung je Abschnitt. Nur vorhandene
Seiten-Darstellung und eigene Styles/Textbausteine werden geändert.

## Nachweise

- Memory/SQLite: Vertrag jenseits der ersten 100 globalen Einträge, korrekte
  Mieternamen, mehrere aktive Verträge, vollständige begrenzte Cursorstrecken,
  einheitsspezifische Versicherungen, keine globalen Listenzugriffe.
- Rechte: fremde Einheit unsichtbar; Cursor an Benutzer/Scope/Einheit gebunden;
  Rechteentzug vor Veröffentlichung; SQL liest ohne fremde pending-DML.
- HTTP: authentifiziert, private/no-store, fremde Einheit und ungültige Queries.
- UI: positive/Null/fehlende Beträge, echte Seitenwechsel, rascher Einheiten-
  und Benutzer-/Scopewechsel, verspätete Antworten, sichtbarer Fehler/Retry.
- Gezielt relevante bestehende Vertragsworkspace-Gates, Ruff, Typprüfung,
  UI-Tests und Produktionsbuild; Ergebnisse mit Sourcezustand im Handoff.

## Folgeschritt für die Legacylisten

Nach diesem abgegrenzten Nachweis wird die gemeinsame Serverlisten-Schnittstelle
geplant: typisierte Filter und stabile Cursor, getrennte vollständige Kennzahlen,
explizite Fehlerzustände, Suchreferenzen und serverseitige Exporte. Die übrigen
Seiten werden in diesem Paket nicht spekulativ massenhaft umgestellt.
