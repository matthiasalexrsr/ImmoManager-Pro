# Immobilien-, Einheiten-, Vertrags- und Dokumentakten: Prüfung vom 21.10.2026

## Grundlage

Claudes vollständiger Stand `ebcd434840b19f9ab7a940eaea02c5a8d40bdacc` ist die Grundlage.
Er enthält seinerseits die vorherige Finanzaktenprüfung `34e166ee`.
Dokumentseiten, Fassungen, Suchindex, Aufbewahrung, Briefvorlagen, SEPA und persönliche
Dashboardkacheln bleiben enthalten. Seine PDF-Prüfskriptkorrektur `125c5994` wird beibehalten.

## Bestätigte Fehler und Korrekturen

- Immobilien- und Einheiten-PATCH durchlaufen dieselbe vollständige Zuordnungsprüfung
  wie PUT. Ein fehlender Elternsatz wird vor dem Schreiben verständlich abgelehnt.
- Eine bereits mit Fachvorgängen verknüpfte Einheit kann nicht einer anderen Immobilie
  zugeordnet werden und dabei Verträge, Termine oder Belege widersprüchlich zurücklassen.
  Unbenutzte Einheiten lassen sich weiterhin korrigieren. Aufgaben, Termine und
  Versicherungen gehören auch zum Löschschutz einer Einheit.
- Negative Mietvorgaben, Bewohner- und Zimmerzahlen sowie leere Einheitenbezeichnungen
  werden bei neuen Eingaben abgelehnt. Bestehende fehlerhafte Vorgaben bleiben lesbar und
  korrigierbar. Ein Vertrag mit ungültigen alten Mietvorgaben wird vor dem Anlegen geprüft,
  damit die anschließende Anlage des Mietverlaufs keinen halbfertigen Vertrag hinterlässt.
- Der Vertragsdienst berücksichtigt `unit_id` vor der Seitenauswahl. Die Einheitenakte
  muss deshalb keine vollständige fremde Vertragshistorie laden.
- Dokumente in Objekt- und Einheitenakten berücksichtigen auch indirekte Zuordnungen
  über Einheit bzw. Mietvertrag. SQL filtert mit Unterabfragen vor der Pagination;
  Original-Metadaten bleiben unverändert und Dokumente werden nicht vervielfältigt.
  Bestehende Portfolio-Berechtigungen gelten auch für die neuen Abfragen.
- Dokumentdetails liefern einen gesonderten aufgelösten Kontext. Immobilie, Einheit,
  Vertrag und Partei werden auch bei indirekter Zuordnung korrekt verlinkt.
- Die Schnellansichten von Dokumentliste, Immobilienakte und Parteienkarte zeigen die
  aktuelle archivierte Fassung statt einer inzwischen überholten Upload-Datei.
  Originale und alle Fassungen bleiben erhalten. Ladefehler haben eine Wiederholung;
  sie führen nicht stillschweigend zu einer alten Datei.
- Ein Konflikt beim Fassungsupload bindet Wiederholungen nicht dauerhaft an einen
  veralteten Bearbeitungsstand. Verlorene Antworten behalten ihren Wiederholungsschlüssel.
  Verschiedene Dateien mit gleichem Namen, gleicher Größe und gleichem Änderungsdatum
  bekommen getrennte Befehle.
- Die Vermietungsquote der Immobilienliste zählt tatsächlich vermietete Einheiten im
  Gesamtbestand. Fehlende Mietvorgaben sind keine Nullmieten; erfasste Zwischensummen
  bleiben gekennzeichnet. Eine ausdrücklich erfasste Nullmiete gehört zum Durchschnitt.

## Bedienabläufe

- Einheitenakte → zugehörige Dokumente → vollständige Dokumentakte → konkrete
  Immobilie, Einheit, Vertrag oder Partei. Die Übersicht zeigt fünf aktuelle Dokumente
  mit einem Weg zur vollständigen, filterbaren Liste.
- Vertrag → Vertragsdokumente; Dokumentliste mit sichtbarem Objekt-, Einheiten- oder
  Vertragskontext und einer Aktion zum Aufheben des Filters.
- Uploads aus einem Objektkontext übernehmen diesen auch bei mehreren Dateien.
- Zuordnung direkt in der Dokumentakte bearbeiten, mit vollständigen, wiederholbar
  ladbaren Auswahllisten. Einheiten folgen der Immobilie, Verträge der gewählten
  Immobilie/Einheit/Partei. Eine Vertragswahl ergänzt ihre zugehörigen Stammdaten.
- Namensgleiche Einheiten tragen die Immobilie in ihrer Auswahlbezeichnung.
- Immobilienakten verwenden für historische Verträge auch archivierte Parteiennamen.
- Die Einheitenliste zeigt fehlgeschlagene Stammdatenquellen ausdrücklich, unterstützt
  den Objektfilter und verwirft überholte Ladeantworten.

## Reproduzierbare Abnahme

`backend/tests/test_estate_workspaces.py` prüft beide Speicherarten, ungültige Eltern,
verknüpfte und unbenutzte Einheiten, ungültige alte Mietvorgaben, indirekte Dokumente,
Seiten mit 1.001 Dokumenten und beschränkte Benutzer. Der PostgreSQL-Lauf dieses Moduls
ist in der CI verpflichtend und unabhängig von den SQLite-Prüfungen.

Frontend-Regressionen liegen in `EstateLists`, `DocumentAssociations`,
`CurrentDocumentViewer`, `DocumentDetail`, `ContractsTenantCache` und den vorhandenen
Akten-/Navigationsprüfungen. Die allgemeinen Upload-Dateiwerkzeuge bleiben separat geprüft.

`scripts/application_browser_qa.mjs` führt tatsächliche Zuordnungsänderungen und
Fassungsuploads aus, vergleicht heruntergeladene aktuelle und ursprüngliche Bytes und
prüft die Verknüpfungen. Alle 59 ermittelten Seiten werden bei 320, 360 und 1440 Pixeln
geöffnet. Diese Prüfdaten entstehen ausschließlich in einer isolierten Testinstallation.

Vor der Umstellung der Hauptinstallation sind zusätzlich erforderlich: erfolgreiche CI
für den exakten Commit, neu gebautes Windows-Paket, native Browserläufe, vollständiges
Backup, Wiederherstellung mit diesem Paket und explizite Migration. Die geerbten
Migrationen von Claude sind Bestandteil der Abnahme. Die Hauptdaten erhalten keine
fachlichen Testdatensätze. PR #37 bleibt ohne Benutzerentscheidung ungemergt.
