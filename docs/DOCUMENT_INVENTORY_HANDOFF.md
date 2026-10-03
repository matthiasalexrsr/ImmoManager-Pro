# Vollständige Dokumentliste — zweite Lieferung von Package B

Basis `0601fe9` auf `5e636e0`, Branch `assist/bounded-legacy-lists`, 2026-10-03.

## Umsetzung und Kompatibilität

Additive Routen `/documents/inventory/page`, `/summary`, `/export` lassen
bestehende Dokument-CRUD-, Upload-, OCR-, Original- und Versionsrouten bestehen.
SQL filtert vor LIMIT: Titel/Tags/Zuordnungen, Immobilie/Einheit/Vertrag, Typ,
Datum und Prüfansichten. Signierte Cursor binden Benutzer, Scope, Filter und
Sortierung; NULLs und identische Werte haben einen stabilen ID-Tiebreaker.
Die Listenprojektion enthält kleine Metadaten und berechtigte vererbte Namen.
Große Analyse- oder Beschreibungstexte werden nicht in jede Listenzeile geladen.

Unabhängige SQL-Aggregate und vollständige CSV-Quellen umfassen alle passenden
berechtigten Dokumente, unabhängig von sichtbarer Seite oder Cursor. Export in
begrenzten Snapshot-Batches prüft Anmeldung, Scope und frische berechtigte
Projektion vor jedem Batch. Die Tests ändern eine spätere Zeile durch eine
zweite SQL-Verbindung und belegen den Abbruch mit Konflikt statt Mischbestand.
Memory verwendet weiterhin begrenzte Live-Seiten. Der Browser lädt erst nach
vollständigem Empfang herunter; sein Blob benötigt den Speicher der fertigen
Datei. Persistente, wiederaufnehmbare Exportaufträge bleiben ein Folgepaket.

Dokumente zeigen nur den tatsächlich gespeicherten Analysestatus an:
`ai_analyzed_at` belegt vorhandene Analysedaten, keinen laufenden OCR-Auftrag.
Vor Bearbeiten wird der vollständige exakte Datensatz einschließlich Revision
nachgeladen. Fehler erhalten Formulareingaben. Bounded Referenzpicker lösen
Auswahl-IDs gezielt auf und vermeiden Gesamtbestandslisten. Benutzerwechsel
entfernen private Inhalte/Formulare; laufende Reads und Uploads werden verworfen.

Vorhandene OCR-Fehlerbehandlung, Vorschau und Versionshistorie bleiben erhalten.
Dateiauswahl ist jetzt auch im Erstellen-Dialog verfügbar; die Uploadfläche
funktioniert per Tastatur. Die neuen Listen verwenden eigene Komponenten und
bereits bewährte lokale Picker/Lesehilfen. DataTable, FormModal, globale Styles,
Layout, Search, Housing und Billing wurden nicht geändert. Keine Migration.

## Nachweise

- Kombinierte Memory-/SQLite-Backendfälle: **46 bestanden, 4 erwartete
  Memory-Skips**, 167,57 s. Treffer an Position 101/1001/10001, vollständige
  10.002-Zeilenquellen/CSV, Scope/Aggregate/NULL-Sortierung, Cursorbindung,
  keine globalen Listen oder Autoflush, reale Exportkonkurrenz.
- Tatsächliches PostgreSQL über strikten Gate-Runner ohne Skips: je **2 Fälle
  Einheiten und Dokumente** (vollständige 10.002-Zeilenquellen/CSV und stabile
  Sortierung; 45,72 s und 60,94 s), zusätzlich **2 Exportkonkurrenzfälle**,
  26,12 s. Ausschließlich synthetische UUID-Schemas auf dem vom Plattform-Agenten
  kontrolliert gestarteten Testcluster; keine Produktivdaten.
- UI: **46 bestanden in 4 Dateien**, 12,49 s: Units 10, Documents 10,
  vorhandene OCR-Fälle 6 und Versionshistorie 20. Fehler/Entwurferhalt,
  veraltete Antworten, Scope-/Benutzerwechsel, vollständige Exportquellen.
- Echter Edge, frische synthetische SQLite-App: **4 bestanden**, 2,6 min.
  Units und Documents einschließlich 320/360/1440, Folgeseiten und vollständigem
  Export; Versionsupload mit verlorener Antwort/Wiederholung/Wiederherstellung
  und frischen eingeschränkten Logins; private Bild-/PDF-Uploads und Vorschau.
  Die vorhandenen Browserfälle suchen gezielt ihren Datensatz, weil er bei
  vollständiger Seitennavigation nicht zwingend auf der ersten Seite liegt.
- Screenshots der finalen Desktop-/Mobilansichten visuell geprüft. Kein
  horizontaler Seitenüberlauf; die breite Fachtabelle besitzt eigene Navigation.
- Scoped ESLint, Ruff, Mypy Ziel 3.11 und 3.12, Produktionsbuild erfolgreich.

Belege: `bounded-lists-backend.log`, `bounded-lists-pg-races.log`,
`bounded-lists-ui.log`, `bounded-lists-e2e-final.log`, vorherige getrennte
`unit-inventory-pg.log` und `document-inventory-pg.log`. Der erste kombinierte
Browserlauf hatte einen überholten Selektor im bestehenden Versionstest;
der finale komplette Lauf oben ist erfolgreich. Browserbilder liegen unter
`frontend/test-results` und sind lokale, ignorierte Prüfartefakte.

## Folgelieferung

Als nächstes Wartungs-/Schadensliste: den 10.000-Zeilen-Zwischendeckel bei
Datumsfiltern durch berechtigte SQL-Filter ersetzen, vollständige Kennzahlen,
Cursorseiten, CSV und bounded Referenzen. Vor diesem nächsten Fachadapter
können jetzt belegte gemeinsame Export-/Cursor-/React-Teile gezielt konsolidiert
werden. Danach Kontakte/Mieter und übrige Altlisten einzeln; keine pauschale
Umschreibung aller Seiten. Indizes oder neue dauerhafte Exporttabellen werden
vor einer Migration separat mit dem Root reserviert.
