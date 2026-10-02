# Buchungen über viele Jahre: begrenzte Seiten und vollständiger Export

`GET /api/v1/bookings/page` liefert `items`, `next_cursor` und `has_more`.
Es liest eine begrenzte Seite mit Datenbankfiltern, ohne die komplette
Buchungstabelle in den Browser zu laden. Es gibt keine Obergrenze für Jahre,
Gesamtbestand oder die Anzahl weiterblätterbarer Seiten.

Die feste Reihenfolge ist `booking_date DESC, id DESC`. Der ID-Tiebreak verwendet
in SQLite `BINARY` und in PostgreSQL `C`, damit Datenbanklokalisierungen die
Reihenfolge nicht gegenüber der Python-Referenz ändern. Die fünf zusätzlichen
Indizes unterstützen die ungefilterte Ansicht sowie Konto, Immobilie, Mieter und
Status. Migration `l1a2b3c4d5e6` folgt auf `k1a2b3c4d5e6` und verändert keine
Geschäftsdaten; ihr Downgrade entfernt nur diese zusätzlichen Indizes.

Ein Aufruf akzeptiert `account_id`, `property_id`, `tenant_id`, `status`
(`open`, `matched`, `booked`, `confirmed`), `date_from`, `date_to`, `search`, `view`,
`page_size` und `cursor`. Datumsfilter verwenden `YYYY-MM-DD`. `search` sucht
literal nach Buchungstext oder ID; `%` und `_` werden nicht zu Wildcards.
Suchtexte sind auf 200 Zeichen begrenzt. `view` ist `all`, `uncategorized`,
`no_receipt`, `income` oder `expense`. Fremde Sortier- oder Spaltennamen sind
keine SQL-Eingaben und werden abgewiesen.

Standardmäßig werden 100 Datensätze pro Seite übertragen. Der serverseitige
Übertragungsrahmen wird durch `BOOKING_PAGE_MAX_SIZE` festgelegt
(Standard 500, validierbarer Bereich 25–5000). Er begrenzt eine einzelne Antwort,
keine Bestandsgröße. Jede SQL-Seite liest höchstens `page_size + 1` Datensätze;
es wird keine globale `COUNT`-Abfrage und kein wachsendes `OFFSET` benötigt.
Kleine referenzierte Anzeigenamen werden innerhalb derselben begrenzten Abfrage
über Schlüsselverknüpfungen geliefert. Der Memorypfad hält zusätzlich höchstens
eine Seite im Auswahlheap und ist weiterhin ein explizit transienter Testmodus.

Der versionierte HMAC-Cursor bindet die normalisierten Filter, Seitengröße,
Sortierung, Benutzer, Rolle, Portfoliozugriff und letzte tatsächlich gelesene Position. Ein Cursor ist keine
Zugangsberechtigung: alle Aufrufe verlangen weiterhin die normale Anmeldung.
Manipulation, abgelaufene Cursor (eine Stunde) und Filterwechsel liefern HTTP 400
mit einem maschinenlesbaren `clear_code` und `recovery=restart_page`.
Der Client beginnt nach einer ausdrücklichen Neuladung wieder bei der ersten
Seite; er erfindet keinen neuen Cursor und wiederholt keinen anderen Filter
stillschweigend. Bei Schlüsselrotation werden alte Cursor ebenfalls ungültig.

Die Seitenansicht ist eine Liveansicht. Neuere Buchungen erscheinen beim
Neuladen der ersten Seite. Später eingefügte ältere Buchungen können auf folgenden
Seiten erscheinen. Verschobene oder gelöschte Buchungen verändern die Liveansicht;
für einen unveränderten vollständigen Datenstand dient der Export.

## CSV aus einem konsistenten Snapshot

`GET /api/v1/bookings/export.csv` akzeptiert dieselben fachlichen Filter, jedoch
keine Cursor-/Seitenparameter. Es exportiert sämtliche passenden Zeilen,
einschließlich mehr als 10.000, aus einem eigenen Lesesnapshot. SQLite verwendet
einen ausdrücklichen Lesetransaktionsbeginn, PostgreSQL `REPEATABLE READ` und
`READ ONLY`. Der erste Lesezugriff erfolgt vor Ausgabe des Headers. Unabhängige
spätere Änderungen oder Einfügungen ändern die laufende Datei nicht.

Der Export erfasst den Portfoliozugriff bereits im ursprünglichen Request,
bevor ein Iterator im Worker läuft. Vor Kopfzeile und jedem Datenabschnitt
werden Benutzerstatus, Rolle und Portfoliozuordnung frisch geprüft. Ein
Rechtewechsel bricht den Stream mit Fehler ab. Bei ausgewählten Portfolios
prüft eine unabhängige aktuelle Verbindung außerdem die Sichtbarkeit aller
Zeilen des nächsten Abschnitts: auch eine verschobene Buchung oder Immobilie
darf durch den älteren Lesesnapshot keine Daten mehr liefern. Der Memorypfad
prüft die aktuellen Zeilen und Elternzuordnungen entsprechend. Es werden
keine stillen Teilergebnisse als vollständiger Export abgeschlossen.

SQL wird in Schritten von 1000 Datensätzen gelesen und als UTF-8-CSV mit BOM und
Semikolon übertragen. Die Datei wird serverseitig nicht vollständig gesammelt.
Verdächtige Formelpräfixe in Textzellen erhalten ein Apostroph; echte negative
Beträge bleiben Zahlen. Der private Snapshot wird bei Abschluss, Lesefehler oder
Clientabbruch geschlossen. Ein großer Export kann während seiner Dauer einen
Datenbanksnapshot festhalten; das ist für den konsistenten Datenstand erforderlich.

## Integration und überprüfbarer Lastnachweis

Die Buchungsoberfläche verwendet ausschließlich `/bookings/page` für ihre
Ergebnisliste. Suche, Zeitraum, Status, Ein-/Ausgaben und fehlende Zuordnungen
werden vor der Seitenauswahl im Backend geprüft. Die Summen sind ausdrücklich
als Werte dieser Seite bezeichnet. Weitere Seiten bleiben abrufbar; ein
Cursorfehler bietet eine ausdrückliche Aktion für einen Neustart mit denselben
Filtern. Veraltete Antworten werden nach Filterwechsel oder Schließen ignoriert.

`GET /api/v1/bookings/lookup/{kind}` liefert begrenzte Auswahlseiten für
`accounts`, `categories`, `properties`, `units` oder `tenants`. Freie Tabellen-
oder SQL-Namen sind ausgeschlossen. Suchbegriffe sind auf 200 Zeichen begrenzt,
die übertragenen Seiten auf die konfigurierte technische Größe. Die tatsächlich
ausgewählte ID wird separat exakt gelesen, auch wenn sie außerhalb der Seite
liegt. Die separate Auswahlprüfung ist ebenfalls auf erlaubte Portfolios
begrenzt. Signierte Auswahlcursor binden Art, Suche, Seitengröße und
Benutzerzugriff. Fehler bleiben
sichtbar und wiederholbar. Diese Endpunkte übernehmen die reguläre
Installationauthentifizierung und erlauben genehmigten Lesekonten die Auswahl.

Der Editor übernimmt den ursprünglichen Bearbeitungsstand der geladenen
Seitenzeile. PUT und DELETE senden dessen `If-Match`, einschließlich aller sechs
Nachkommastellen. Ein ausdrücklicher Konfliktabgleich synchronisiert seine
Fremdschlüsselauswahl über die optionale FormModal-Prop `onValuesChange`; ein
neuer Serverwert wird auch außerhalb der aktuellen Auswahlseite dargestellt.
Rechteentzug schließt den Editor und verhindert, dass eine alte Löschbestätigung
nach späterer Rechtefreigabe wieder wirksam wird.

„CSV herunterladen“ lädt alle Treffer mit den angewandten Filtern. Der Browser
sammelt hierbei die Downloadbytes als Blob. Für große Dateien bietet ein
unterstützender Browser zusätzlich „CSV direkt speichern“: eine ausdrücklich
ausgewählte Datei erhält den echten Response-Stream über `pipeTo`, ohne einen
vollständigen Blob im Anwendungsspeicher. Zugangs-Token stehen ausschließlich
im Authorization-Header an die eigene API; der Dateidialog erhält keine Token.
Lesefehler brechen den Schreibstream ab und bleiben für einen neuen Versuch
sichtbar. Es gibt keine Zeilenanzahl- oder Jahresgrenze für beide Exporte.

Die kompatible GET-Liste behält Offset/Limit und vorhandene Sortierspalten.
Datums- und Zuordnungsfilter werden in SQL vor dem Limit ausgeführt; der frühere
10.000-Zeilen-Zwischenschritt entfällt. Der Memorypfad filtert ebenfalls vor dem
Slice. Historische reduzierte Tabellen erhalten ausschließlich Indizes, deren
Spalten tatsächlich existieren; vorhandene Geschäftsdaten werden nicht ergänzt
oder umgeschrieben.

Die Rootintegration registriert `backend.db.booking_indexes` vor `create_all`
und Alembic-Metadaten und ruft für historische lokale Datenbanken
`ensure_booking_indexes(connection)` auf. Die serverseitige Einstellung gehört
in die zentrale validierte Settings-Klasse; der Leseservice verwendet während
dieser additiven Integration den Standard 500.

Die Tests verwenden eigene SQLite-Dateien sowie echte PostgreSQL-Schemata,
wenn `TEST_SERVER_DATABASE_URL` ausdrücklich auf einen Wegwerfdienst gesetzt ist.
Sie prüfen Cursorprüfung, alle Filter, Datums-/ID-Gleichstände, konkurrierende
Einfügungen, Snapshot-Erhalt, Export oberhalb von 10.000 Datensätzen und
Verbindungsrückgabe nach Abbruch. Es werden keine Benutzerdatenbanken geöffnet.

Die zusätzliche Lastmessung ist reproduzierbar:

```powershell
.venv\Scripts\python.exe scripts/benchmark_booking_pages.py --rows 100000 --output work/booking-scale-100k.json
# Optional, ausdrücklich außerhalb der normalen Test-Suite:
.venv\Scripts\python.exe scripts/benchmark_booking_pages.py --rows 1000000 --output work/booking-scale-1m.json
```

Das Skript erzeugt ausschließlich eine eigene temporäre synthetische Datenbank,
misst Seitenzeit und CSV-Durchsatz und liefert `EXPLAIN QUERY PLAN` für die
ungefilterte und kontoabhängige tiefe Position. Es misst mit `tracemalloc` die
Python-Allokationen, nicht den gesamten Betriebssystem-/Treiber-RAM. Die Messwerte
sind ein lokaler Beleg, keine hardwareunabhängige Latenzgarantie.
