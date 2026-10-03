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

Unabhängiger Quellenreview präzisiert: Cursorseiten sind laufende Seiten, kein
festgeschriebener Gesamtstand. SQL-CSV verwendet einen tatsächlichen Snapshot
mit erneuter aktueller Projektion-/Rechteprüfung; Memory-CSV bleibt pro Batch
gelockt und live, ohne behaupteten Gesamtsnapshot. Ein UTC-Überlauf an den
darstellbaren Datumsgrenzen wird als Validierungsfehler gemeldet, nicht gekappt.

Erste native Auswahl: 7 PASS/2 FAIL in32,71 Sekunden, hard180. Die beiden
HTTP-Fälle erreichten korrekt200/private-no-store, scheiterten aber an einer
neuen zu engen Headerassertion: CORS ergänzt legitimes `Origin` zu `Vary`.
Prüfung verlangt weiter ausdrücklich `Authorization` als einzelnes Headerfeld.
Gezielter Follow-up umfasst diese beiden echten SQL-HTTP/Revoke-Fälle, einen
echten historischen SQLite-NULL-Zeitfall und zwei UTC-Überläufe: 5 PASS in18,31
Sekunden, hard90, keine Skips. Damit12 unterschiedliche positive Backendfälle
komponiert, keine behauptete komplette12er-Grünwiederholung. Beide Prozesse
normal beendet, keine PostgreSQL-Ausführung oder private Daten in diesen Gates.

Der echte PostgreSQL-Gate auf `d3f5424` liefert2 PASS/1 FAIL in34,50 Sekunden,
hard90: vollständiger10002er-Bestand/CSV und polymorphe Rechte bestehen; das
Zeitintervall zählt0 statt3. Der tatsächliche ORM-Default ist aware UTC, die
physische Spalte TIMESTAMP WITHOUT TIME ZONE. PostgreSQL wandelt den vom
Treiber als TIMESTAMPTZ gebundenen Wert mit seiner Sessionzeitzone um. Der
echte bisherige Repositorywriter hat denselben Fehler; keine reine Testabweichung.

Vor Korrektur festgelegt: UTC-naiver Bindtyp ausschließlich für
ChangeHistoryORM.changed_at, mit unverändertem physischen DateTime-DDLtyp.
Aware Werte ausdrücklich nach UTC und dann ohne tzinfo binden. Naive Werte
und bestehende historische Bytes erhalten; keine serverweite Zeitzonenänderung
oder automatische historische Zeitkorrektur. Mehrdeutige alte PostgreSQLzeiten
bleiben ein ausdrücklich offener historischer Prüfpunkt. Erweitere die echte
PG-Abnahme um den tatsächlichen add_change_history-Default unter zwei eigenen
Sessionzeitzonen. Prüfe diese Fehlerregression sowie Typ/SQLitebindung; die
bereits grünen großen PG-Quellen-/Export-/Scopefälle nicht ohne Anlass wiederholen.

## Native Oberfläche: tatsächlicher erster Fehler und Korrekturplan

Auf `460f812` baut die native Edge-Abnahme 725 Module und die frische,
synthetische SQL-Installation bis K2 erfolgreich. Der einzige Browserfall
erreicht echte Anmeldung, 10002 Treffer, 25 Zeilen und vollständige lange
Werte bei 1440px. Bei 360px scheitert die unveränderte Prüfung der gesamten
Dokumentbreite nach 6,7 Sekunden; Export, Folgeseiten und Rechteentzug werden
dadurch noch nicht erreicht. Die Fehleraufnahme zeigt den nach rechts
versetzten Inhalt. Der gemeinsame Shell-Stil animiert `margin-left` auch
beim Wechsel auf den mobilen Vollbreiteninhalt. Ein historischer Desktop-
Abstand plus bereits mobile Breite erzeugt während dieses Wechsels Überlauf.
Fehlerbild, Desktopaufnahme und Trace sind vor Wiederholung geschützt unter
`artifacts/B_HISTORY_BROWSER_460f812_FAILED` abgelegt.

Vor Korrektur festgelegt: mobile Shell ohne Animation dieses Desktopabstands;
die Navigation behält ihre eigene Drawer-Animation. Die Historie erhält auf
schmalen Bildschirmen lesbare Eintragskarten innerhalb derselben Tabelle,
vollständige Details und erreichbare Spaltenbeschriftungen. Die übrigen
Inventartabellen werden nicht umgestaltet. Browserprüfung bleibt streng,
ergänzt tatsächliche Layoutmaße und wird als genau derselbe Fall wiederholt.
Erst ein kompletter Durchlauf belegt Export und Rechteentzug; vorhandene
fehlgeschlagene Belege werden nicht als Abnahme bezeichnet.
