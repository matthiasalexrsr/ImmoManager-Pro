# Package B: Einheiten und Dokumente

Basis `5e636e0`, eigener Branch `assist/bounded-legacy-lists`. Zuerst Einheiten,
danach Dokumente als getrennte überprüfbare Commits. Gemeinsame Helfer erst
nach diesen beiden Fachadaptern konsolidieren.

## Zuständigkeit und Kompatibilität

- Eigene `unit_inventory*`-/`document_inventory*`-Services, Router und Tests;
  minimale Routeranbindung in `units.py` und `documents.py` vor dynamischen IDs.
- Eigene Frontendmodule und scoped Styles; Einheiten-/Dokumentseiten gezielt
  anbinden. Bestehende GET-Listen, DTOs und CRUD bleiben unverändert verfügbar.
- Keine Änderung an Root-/Search-/Housing-/Billing-/Layout-Dateien, globalem
  DataTable, FormModal, Workflowpickern oder globalem Datencache. Vorhandene
  FormModal-Kinder erlauben unabhängige Suchpicker; versteckte IDs bleiben Teil
  des Formulars und bestehender Revisionsschutz wird explizit weitergereicht.
- Keine Migration. Performance und Abfragepläne prüfen; notwendige Indizes
  danach dem Root mit konkreter Migrationreservierung vorschlagen.

## Leser, Kennzahlen, Exporte

Neue `/units/inventory/page`, `/units/inventory/summary`,
`/units/inventory/export` (analog Dokumente). Filter/Suche vor SQL LIMIT,
eindeutige Sortierung mit ID, NULLs zuletzt, query-/scopegebundene signierte
Cursor. Kleine Namensprojektionen statt Gesamtbestandsreferenzen. Seite hat
`items`, `has_more`, `next_cursor`; Summary berechnet über genau dieselbe
gefilterte berechtigte Menge, unabhängig vom Cursor. Fehler niemals zu Null
oder Leerbestand umdeuten.

Einheiten unterscheiden gespeicherten Status, vorhandene Verträge und Anzahl
aktiver Verträge. Nur genau eine aktive Partei wird namentlich als eindeutig
dargestellt; mehrere Verträge bleiben als solche sichtbar. Warmmiete nur bei
vollständigen Komponenten, fehlender Betrag nicht still als Null. Kennzahlen
geben Nenner und fehlende Werte an; keine erfundene Leerstandsdauer aus dem
Erstellungsdatum. Nullmieten gehören zum Durchschnitt vorhandener Werte.

Dokumente nutzen echte persistierte AI-Metadaten für den Analysestatus. Das
bisher im Browser gelesene `ocr_status` ist kein Document-Feld; ein bloßes
Dateivorhandensein beweist keine laufende OCR. Original-/Versions-/Viewer-
Workflows und vorhandene Uploadfehlerbehandlung erhalten.

CSV wird vollständig auf dem Server aus derselben berechtigten Filterbasis
gelesen, in begrenzten Batches und einer SQL-Lesetransaktion. Keine Browser-
Seitenexporte, keine globale RAM-Liste. Textformeln absichern. Scope/Anmeldung
und aktuelle Zuordnung werden vor Veröffentlichung und zwischen Batches
erneut geprüft; Abbruch ist ein Fehler, kein erfolgreicher Teildownload.
Memory ist Referenzbetrieb mit begrenzter Auswahl, kein Produktionssnapshot.

## Bedienung

Suche, fachliche Filter und Sortierung bleiben bei Fehlern erhalten. Benutzer-
und Rechtewechsel entfernen private Ergebnisse und offene Formulare synchron;
Requests werden abgebrochen und an ihre genaue Quelle gebunden. Listen- und
Summaryzustand getrennt. Cursorfehler ermöglichen Neustart. Eingaben bleiben
bei Speicherfehlern erhalten. Bounded Referenzsuche nutzt bestehende
`/workflow-references` inklusive exakt aufgelöster ausgewählter ID; wechselnde
Immobilie/Einheit darf keine unpassende Referenz stillschweigend speichern.

Tastaturbedienbare Tabellen/Aktionen, ruhige Abstände, klare Fehler und 320-,
360- und 1440-Pixel-Layouts. Bestehende einfache lokale Tabellen bleiben im
bisherigen Modus, bis deren jeweiliger Fachadapter nachgewiesen ist.

## Abnahmen pro Lieferung

- Treffer 101/1001/10001, vollständige Cursorfolge und scoped Summen/Exporte;
  gleiche Sortierung bei NULLs/Gleichständen auf Memory, SQLite und echtem PG.
- Globale Listenmethoden verboten; bounded SQL, kein Autoflush fremder DML;
  quer geklebte Cursor sowie Actor-/Scope-/Filterwechsel abgewiesen.
- Reale Referenzwahl jenseits erster Seiten, Rechteentzug bei Read/Export,
  SQL-Snapshot und reale Updates während Export. Kein versteckter Gesamtdeckel.
- UI-Races, explizite Fehler/Retry, kein Verlust von Such- oder Formulareingaben,
  Revisionskonflikte. Echter Browser mit neuer synthetischer SQLite-App,
  vollständigem CSV, Anlegen/Ändern und schmalen Viewports.
- Ruff, fokussierte Typ-/UI-Prüfungen, Produktionsbuild, bestehende relevante
  Vertrags-/Dokument-/Berechtigungsregressionen; genaue Belege im Handoff.
