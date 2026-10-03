# Paket B: Vollständige Änderungshistorie

## Tatsächlicher Ausgangspunkt

Root `37e8451`: `History.jsx` fordert ausschließlich `/history?limit=500` an.
Der alte Router materialisiert und sortiert zuvor `list_change_history()`.
Die Oberfläche erwartet `action` und `username`, obwohl die gespeicherten
Feldänderungen ausschließlich `field_name`, `changed_by` und `reason` besitzen.
Die vorhandene Portfolioabgrenzung kennt polymorphe Historienbezüge bereits.
Diese Berechtigung wird übernommen, nicht durch eigene Objektregeln ersetzt.

## Abgegrenzte Umsetzung

1. Additive `/history/inventory/page`, `/summary` und `/export` vor den
   dynamischen Historienrouten. Seiten, SQL-COUNT und Export verwenden dieselbe
   berechtigte Filterbasis; keine Migration oder Startup-DDL.
2. Serverseitige Unicode-Suche in Kennungen, Feld, Grund und gespeicherten
   Werten; exakte Filter für Entität, Entitätskennung, Feld und Benutzerkennung.
   Freier UTC-Zeitraum mit inklusivem Anfang und exklusivem Ende. Keine
   behauptete Benutzer-Namenszuordnung oder erfundene Änderungsaktion.
3. Feste Reihenfolge: Änderungszeit absteigend, fehlende Zeit zuletzt,
   byteweise ID absteigend als Gleichstandsauflösung. Signierte Cursor binden
   Filter, Seitengröße und aktuellen Actor-/Portfoliostand. SQLite-Sekunden und
   ORM-Mikrosekunden benötigen dieselbe Vergleichsdarstellung; PostgreSQL
   behält typisierte Zeitvergleiche. Memory verwendet begrenzte Top-Auswahl.
4. `no_autoflush`, frische Rechte vor und nach dem Lesen und die vorhandene
   Veröffentlichungssperre vor der HTTP-Antwort. Kein paralleler Fremd-DML.
5. Alter GET-Listenvertrag bleibt eine Liste mit `skip`/`limit`, wird aber
   serverseitig begrenzt. Der historische unpaginiert vollständige
   Entitätsaufruf bleibt kompatibel und wird von der neuen Oberfläche nicht
   verwendet; seine Ablösung ist ausdrücklich noch offen.
6. Vollständiger CSV-Export über den bestehenden Batch-/Snapshotexporter,
   unabhängig vom sichtbaren Cursor, mit Formelabsicherung und erneuter
   Daten-/Rechteprüfung. Ein abgebrochener Export gilt nicht als vollständig.
7. Eigene Historienansicht mit Suche, Filtern, vollständiger Trefferzahl,
   Folgeseiten, aufklappbaren vollständigen Werten/Grund und CSV. Ladefehler,
   Leerbestand und fehlende Angaben unterscheiden. Änderungen von Anmeldung
   oder Rechten entfernen alte Ergebnisse synchron; Fokus, Aktualisierung und
   Export prüfen `/auth/me`, alte Antworten werden verworfen.

## Prüfungen und Grenzen

- Treffer 101/1001/10001, vollständige Cursorfolge, identische Gleichstände,
  tatsächliche gemischte SQLite-Zeitwerte und ein Mikrosekundenabstand.
- Filterbindung, Actor-/Rechtewechsel, polymorphe Objektabgrenzung, SQL-LIMIT,
  kein globaler Listenaufruf oder Autoflush; vollständiger CSV mit Sonderzeichen.
- Echte HTTP-Abnahme mit SQL-Benutzern und Veröffentlichung nach Rechteentzug.
- UI mit verspäteten Antworten, Fehler/Retry, vollständigen Details und
  Exportfilterung; anschließend gezielte native Browserabnahme.
- PostgreSQL-Fall ist verbindlich und wird nur nach tatsächlicher Ausführung
  als bestanden bezeichnet. Kein neuer paralleler Alembic-Head: L2 ist für
  TEHA reserviert. Ein Zeit/ID-Index folgt einer gesonderten, gemessenen
  Leistungsabnahme; aktuelle Speicherbegrenzung beweist keinen Indexzugriff.
- Historie wird hier vollständig gelesen. Die atomare Erzeugung allgemeiner
  Feldänderungen aus Paket L ist ein eigenes, weiterhin offenes Schreibpaket.
