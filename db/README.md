# Datenbankschema

Dieses Verzeichnis enthält das initiale Datenbankschema für ImmoManager Pro.

## Überblick

Die Tabellen bilden die Kernbereiche der Anwendung ab:

- Portfolios, Immobilien und Einheiten
- Mieter, Verträge und Zahlungsströme
- Instandhaltung, Dokumente, Aufgaben und Termine

## Verwendung

1. Datenbank erstellen (PostgreSQL empfohlen).
2. Schema aus `schema.sql` ausführen.
3. In der Applikation die Verbindungsdaten hinterlegen.

## Hinweise

- Alle Tabellen verwenden UUIDs als Primärschlüssel.
- Zeitstempel sind in UTC (`timestamptz`).
- Statusfelder sind als `text` hinterlegt und sollten in der Anwendung über Enumerationen abgebildet werden.
