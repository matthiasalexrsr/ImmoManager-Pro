# Gemeinsamer Exportadapter für die Immobilienübersicht

Die neue Immobilienübersicht verwendet eine dreiteilige Sortierposition aus
Währung, exakter Centzeichenfolge und Immobilien-ID. Die Mietsumme wird auf SQLite
durch ein verbindungslokales Aggregat berechnet; CSV-Ausgaben enthalten öffentliche
Dezimalzeichenfolgen statt der internen Sortierwerte. Der vorhandene vollständige,
berechtigungsgeprüfte Export wird dafür additiv erweitert.

## Verbindlicher Adaptervertrag

- `prepare_read(session, query)` ist optional und bereitet genau die übergebene
  Snapshot- oder Live-Session vor der ersten Datenabfrage vor. Ein vorhandener Hook
  übernimmt auch die Suchvorbereitung. Ohne Hook bleibt die bisherige bedingte
  `ensure_sqlite_casefold`-Vorbereitung erhalten.
- `page_position(query, raw_row)` ist optional und liefert die Fortsetzungsposition
  der letzten Rohzeile. Ohne Hook bleibt `(row[sort_by], row[id])` erhalten.
- `export_row(raw_row)` ist optional und liefert die öffentliche CSV-Projektion.
  Ohne Hook wird die bisherige Rohzeile ausgegeben.

Positionsbildung und frischer DTO-Vergleich bleiben von der Ausgabeformatierung
getrennt. Kein Hook erhält eine zusätzliche Datenbankverbindung oder darf das
Schema ändern. Seitenbudgets begrenzen einzelne Übertragungsschritte, nicht den
Gesamtbestand. Alle drei Hooks werden auch auf dem passenden Speicherpfad benutzt;
die Session-Vorbereitung ist ausschließlich für SQL erforderlich.

## Prüfung und Integration

Die vorhandenen unabhängigen Exportänderungs-, Rechteentzugs-, Formeltext- und
vollständigen Bestandsprüfungen bleiben bestehen. Die Immobilienprüfungen müssen
zusätzlich tatsächliche SQLite-Sessions einschließlich der frischen Vergleichs-
Session, mehrere Währungen, exakte Summen und Fortsetzung über mehr als eine Seite
abdecken. PostgreSQL und MemoryStore erhalten eigene fachliche Nachweise.

Dieses Paket ändert weder bestehende Endpunkte noch eine Migration oder den
laufenden Release 126. Die fachliche Implementierung erfolgt im abgegrenzten
Immobilienpaket; die zentrale Integration verantwortet diesen gemeinsamen Adapter.
