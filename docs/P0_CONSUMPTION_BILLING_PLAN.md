# P0: nachvollziehbare Verbrauchs- und Personenbasis

Plan vor Produktänderungen, Basis `679c8de`, 3. Oktober 2026.

## Fehler und verbindliche Änderung

Die bisherige Abrechnung summiert Wasser, Strom und weitere Medien je Wohnung
zu einem gemeinsamen Verbrauch. Personenanteile verwenden ersatzweise Zimmer.
Beides wird für neu berechnete Abrechnungen beendet. Veröffentlichte Jahre und
Originale werden nicht neu berechnet oder verändert.

- `AllocationKeyCreate`, `AllocationKeyPatch`, `AllocationKey` erhalten die
  optionalen, bearbeitbaren Felder `consumption_medium` und `consumption_unit`.
  Das Medium muss exakt einem `Meter.meter_type` entsprechen; Namen und Notizen
  werden nie als Zuordnung ausgewertet. Fehlende Angaben dürfen gespeichert
  werden und erscheinen bei tatsächlich verwendeten Verbrauchsschlüsseln als
  reparierbare Vorprüfungsblocker.
- `MeterCreate`, `MeterPatch`, `Meter` erhalten `measurement_unit`. Ohne diese
  ausdrückliche Angabe lässt sich eine vorhandene Ablesung nicht zuverlässig
  in kWh, m³ oder sonstige Einheiten einordnen. Keine stillen Konvertierungen.
- ORM und Migration `e2a2b3c4d5e6` nach `d2a2b3c4d5e6` ergänzen diese drei
  nullable Spalten. Altdaten bleiben NULL; die Migration erfindet keine Werte.
  Ein Downgrade verweigert das Verwerfen bereits gepflegter Zuordnungen.

## Rechenweg und Grenzen

Ein eigener reiner Prüfer erzeugt je verwendetem Schlüssel Gewichte und
strukturierte Befunde. Die HTTP-Vorprüfung und die tatsächliche Erzeugung
verwenden denselben Prüfer. Jede betroffene Einheit benötigt passende Zähler,
einheitliche deklarierte Einheiten und mindestens zwei eindeutige, endliche,
nicht fallende Grenzablesungen am Beginn und Ende der Periode. Deaktivierte
Zähler mit passenden Periodenablesungen bleiben historische Quellen. Zähler
ohne Periodenbezug werden durch fehlenden Grenznachweis nicht versehentlich
als Verbrauch von null behandelt. Unterjährige Installationen, Zählerwechsel,
mehrere Mietverhältnisse derselben Einheit und weitere fehlende Teilperioden-
grundlagen erhalten konkrete Korrekturhinweise; ein zukünftiges eigenes Paket
liefert deren datiertes Modell, dieses Paket schätzt keine Verbrauchsanteile.

Einzelne belegte Nullverbräuche sind gültige Nullanteile. Bei Gesamtsumme null
und tatsächlich umzulegenden Kosten muss ein anderer geprüfter Schlüssel
gewählt werden. Negative/falsche/mehrdeutige Werte werden vor Schreiben
abgewiesen. Bei Personenschlüsseln ist eine positive tatsächliche
`Unit.person_count` erforderlich; `rooms` ist nie Ersatz.

## Prüfungen und Integration

Neue echte HTTP-Fälle in Memory und SQLite prüfen getrennte Wasser-/Stromkosten,
den Gegenbeleg 10 m³ + 1000 kWh gegen 10 m³, gemischte Maßeinheiten, Reparatur
fehlender Angaben, Nullverbrauch, historische deaktivierte Zähler, ungültige
Ablesungen, unterjährige Mehrfachbelegung und fehlende Bewohnerzahl. Geänderte
Quellen müssen bestehende Entwurfsfinalisierung invalidieren. Ein bereits
finalisiertes Jahr bleibt byte-/wertgleich und weiter lesbar.

Migrationstests prüfen echte SQLite-DDL mit erhaltenen Zeilen, Beziehungen und
Triggern sowie verlustverweigernden Downgrade. Relevante bestehende Abrechnungs-
und Rundungsfälle werden gemeinsam ausgeführt. Die vollständige lineare
Migration nach dem separat gelieferten d2-Historypaket prüft Root zusätzlich.
Keine UI-, Startup-, History- oder fremden Worktree-Dateien werden verändert.
Die Oberfläche bekommt die drei Feldnamen und Vorprüfungsbefunde im Handoff.
