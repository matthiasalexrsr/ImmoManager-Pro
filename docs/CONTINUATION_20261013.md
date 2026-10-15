# Fortsetzung nach der Claude-Gesamtprüfung

Ausgangspunkt: `7f057000`, geprüfter und veröffentlichter Reviewstand. Die frühere
Wettbewerbsanalyse vom 7. Oktober bleibt als historische Beobachtung erhalten.
Ihre Aussagen über fehlende Portfoliozugriffe, globale Suchseiten, Finanzaggregation,
Wohnungsgeberbestätigung, Übergaben, Objektverträge und Projektakten sind durch die
zwischenzeitlichen Implementierungen überholt. Maßgeblich ist der aktuelle Code.

## Verbindliches nächstes Paket

1. **Echte Mietzahlungen:** Die bisherige Zahlungsschaltfläche in der Mietübersicht
   ändert lediglich `amount_paid`/Status und verwirft eingegebenes Datum und Notiz.
   Sie erzeugt weder Buchung noch Vertragszuordnung. Der neue Ablauf muss eine
   tatsächliche Zahlung mit Konto, Datum, Betrag und Buchungstext atomar erfassen,
   dem gewählten Vertrag zuordnen und Wiederholungen sicher erkennen. Die Übersicht
   muss dieselben gebuchten Beträge wie das Mieterkonto verwenden. Eine Zahlung auf
   den Vertrag darf nicht als gezielte Begleichung einer einzelnen Forderung
   ausgegeben werden, solange keine solche Zuordnung existiert.
2. **Gefilterte, vollständige Berichtsausgabe:** PDF und JSON verwenden dieselben
   Zeitraum-/Portfolio-/Objekt-/Einheitsfilter. Lange Bezeichnungen und Monatsreihen
   werden umgebrochen und über Folgeseiten vollständig ausgegeben. Nicht unterstützte
   Filter müssen abgelehnt werden; fremde Objektnamen bleiben geschützt.
3. **Aktueller Praxistest:** Der alte XStress-Aufbau erstellt inzwischen korrekt
   eingeschränkte Benutzer, weist ihnen aber keine Portfolios zu. Der dadurch
   gescheiterte erste Lauf ist kein Produktbeweis. Der Aufbau erhält ausdrückliche
   Testportfoliozuweisungen und bricht bei fehlenden Grunddaten sofort ab. Die
   tatsächlich geltenden Rollen- und Bestandsgrenzen bleiben eingeschaltet.
4. **Großbestand:** Eine neue isolierte Messung soll 20 Jahre synthetische Daten,
   zunächst 100.000 und danach eine Million Buchungen sowie zehn getrennte Benutzer
   prüfen. Schwerpunkt sind vollständige Finanzaggregate und Suche, nicht erneut
   allein Buchungsseiten. Erwartungen werden unabhängig während der Datenerzeugung
   berechnet. Laufzeiten, Speicher, erfolgreiche Schreibvorgänge und unvollständige
   Phasen werden ausdrücklich protokolliert.

## Berichtsausgabe

- `GET /reports/pdf/{name}` unterstützt die vorhandenen Finanzfilter und für
  `cashflow` zusätzlich die bisherige `months`-Auswahl. `period-result` ist auch
  als PDF verfügbar; seine tatsächlich angewandten ganzen Kalendermonate stehen
  in der Ausgabe. Der Bericht bezeichnet gebuchte Kosten nicht als vollständige
  steuerliche Gewinnermittlung.
- Die Belegung unterstützt Portfolio, Immobilie und Einheit in JSON/CSV/PDF.
  Der PDF-Aufruf verweigert Zeitraumfilter, weil die Belegung den heutigen Stand
  zeigt. `months` bei anderen PDF-Typen wird ebenfalls ausdrücklich abgelehnt.
- Lokale Unicode-Schriften, deutsche Beschriftungen, vollständige Tabellen,
  wiederholte Spaltenköpfe und Seitenzahlen ersetzen die bisherige abgeschnittene
  Ausgabe technischer Feldpfade. Es gibt keinen Textdownload unter dem Anschein
  einer erfolgreich erzeugten PDF-Datei.

## Abnahme

Prüfungen und Messungen laufen in eigenen synthetischen Verzeichnissen. Die
laufende Anwenderinstallation wird nicht migriert. Der vollständige Reviewnachweis
unter `CLAUDE_REVIEW_20261013_VALIDATION.md` gilt für seinen dort eingefrorenen Stand;
neue Ergebnisse dieses Pakets werden getrennt erfasst. Externe TEHA-Schreibvorgänge
und WISO-Steuer-Zielimport bleiben eigene, durch lokale Tests nicht ersetzbare
Abnahmen.

### Bereits abgeschlossene Berichtsprüfungen

- 54 fachliche Berichts-/Finanzprüfungen im Memory-Speicher und dieselben 54 unter
  SQLite bestanden. Nach dem letzten Layoutabgleich bestanden zusätzlich alle zehn
  PDF-Prüfungen unter SQLite. Die Monatsiteration beendet Dezember 9999 jetzt am
  angeforderten Endmonat, statt einen nicht darstellbaren Folgemonat anzulegen;
  der entsprechende Regressionstest bestand ebenfalls.
- Der synthetische Cashflowbericht mit 240 Monaten umfasst neun Seiten. Erste und
  mittlere Seite sowie eine separate Ausgabe mit langen Unicode-Bezeichnungen
  wurden tatsächlich gerendert und visuell geprüft. Automatische Prüfungen erfassen
  Vollständigkeit, Seitenumbrüche und Textpositionen.
- Die Ergebnisse und gerenderten Kontrollbilder liegen lokal unter
  `artifacts/continuation-20261013/pdf/`. Diese synthetischen Prüfdateien gehören
  nicht zum Release und enthalten keine Anwenderdaten.

### Vertragszahlungen

Die neue Mietübersicht verwendet den bestehenden datierten Mietverlauf und echte
Zahlungsbuchungen. Zahlungskonto, Datum und Bemerkung bleiben erhalten. Buchung,
Vertragszuordnung und dauerhafter Wiederholungsbeleg werden gemeinsam gespeichert.
Der bisherige manuelle Status einer Sollstellung gilt nicht länger als Nachweis
eines Zahlungseingangs. Eigenständige Forderungen bleiben gesondert erreichbar.

Die Umsetzung und ihre Wiederaufnahmegrenzen stehen in
[`RENT_PAYMENTS_20261013.md`](RENT_PAYMENTS_20261013.md). Insbesondere bleibt die
lokale Befehlskennung im Sitzungsspeicher desselben Browser-Tabs; eine
geräteübergreifende Wiederaufnahme wird nicht behauptet.

- 78 fachliche Miet-/Zuordnungs-/Kautions-/Finanzprüfungen unter Memory bestanden,
  zwei SQL-spezifische Varianten dort übersprungen.
- Unter SQLite bestanden die verwandten Zuordnungs-/Kautions-/Finanzprüfungen.
  Ein Fehler in den neuen Testdaten (doppelte Vertragsnummer) wurde korrigiert;
  anschließend bestanden alle 26 Fälle der vollständigen Mietzahlungs-Testdatei.
- Der echte PostgreSQL-Test mit drei unabhängigen gleichzeitigen Verbindungen
  bestätigt genau eine Buchung und eine Zuordnung bei drei gleichen Befehlen.
  Der bestehende verpflichtende PostgreSQL-Prüflauf entdeckt die neue Testdatei
  automatisch; übersprungene PostgreSQL-Fälle gelten dort weiterhin als Fehler.
- Neun Oberflächenregressionen bestanden, darunter verspätete Antworten einer
  verlassenen Ansicht und die Wiederaufnahme nach verloren gegangener Bestätigung.
  Lint, Typprüfung der geänderten Backenddateien, gesamter Frontend-Lint und
  Produktionsbuild bestanden.

### Großbestandsprüfung und Suchkorrektur

Die neue isolierte SQLite-Messung prüft 240 Monate, 72.000 Forderungen und bis zu
einer Million Buchungen. Sie enthält unabhängige Cent-Summen, vollständige
Suchseiten und Exporte, eingeschränkte Benutzer sowie zehn gleichzeitig aktive
Benutzer mit Lese- und Schreibzugriffen.

Die Ausgangsversion nahm für jede ASCII-Zeile einen Python-Aufruf zur
Groß-/Kleinschreibung vor. Der SQLite-Pfad verarbeitet ASCII jetzt direkt in der
Datenbank; Unicode behält die bisherige Behandlung. 51 gezielte Suchprüfungen
bestanden. Die Benchmarkprüfungen bestätigen außerdem das unveränderte gesamte
Zeitbudget über Phasenwechsel hinweg.

| Messung | Vorher | Nachher |
| --- | --- | --- |
| 100.000 Buchungen, langsamste Suche bei Parallelzugriff | 8,007 s | 0,951 s |
| 1 Mio. Buchungen, paralleler Ablauf | Suchabbruch nach 30 s | Vollständig bestanden |
| 1 Mio., langsamste Suche / Cashflow im Parallelbetrieb | Kein vollständiger Lauf | 6,496 s / 9,176 s |
| 1 Mio., bestätigte und anschließend einzeln geprüfte Schreibvorgänge | Nachprüfung nicht erreicht | 40 von 40 |

Die erfolgreichen Läufe verwendeten je 60 Sekunden gemischte Last. Der frühere
Millionenlauf dokumentierte seine geplante Lastdauer nicht; sein Abbruch ist kein
Vergleich gleicher Durchsatzfenster. Der neue Millionenlauf erreichte etwa
328 MiB maximalen Anwendungsspeicher und prüfte Exporte mit 10.310 beziehungsweise
3.437 berechtigten Suchtreffern vollständig.

Alle exakten Messwerte, Quellstandnachweise und Einschränkungen stehen in
[`../tools/scale_finance_search.md`](../tools/scale_finance_search.md). Der überwiegend
ASCII-haltige synthetische Bestand ist kein Nachweis für Unicode-lastige Bestände,
PostgreSQL-Leistung, Dokumentarchive oder 20 Jahre simulierte Fachabläufe. Auch die
verbleibenden 6–9 Sekunden für einzelne Lesezugriffe bei einer Million Zeilen sind
ein offener Optimierungspunkt.

### Browser- und Praxistest des integrierten Pakets

Der echte Chromium-Lauf (`scripts/rent_payment_browser_qa.mjs`) besteht alle sechs
Abläufe: Anmeldung und Monatsmiete, echte Teilzahlung mit Datum/Bemerkung,
serverseitig gespeicherte Zahlung mit absichtlich verlorener Antwort und erneuter
Bestätigung nach Neuladen, abgelehnte veraltete Vertragsfassung mit anschließendem
neuem Befehl, schmale Ansichten einschließlich Tastaturbedienung und Nur-Lese-Rolle.
Er läuft ausschließlich gegen einen eigens angelegten lokalen Testserver mit
synthetischen Daten. Chromium 153.0.8010.12; keine JavaScript-Fehler. Ansichten bei
1440, 360 und 320 Pixeln wurden aufgenommen und visuell geprüft; die mobile
Dialogbegrenzung wird zusätzlich gemessen. Browser und Testserver wurden beendet,
der Testport ist wieder frei.

Reproduktion: `QA_BASE_URL` auf eine eigene lokale Testinstanz, `QA_PASSWORD` für
deren Testbenutzer `owner`, `QA_ALLOW_TEST_WRITES=1` und `QA_PLAYWRIGHT_PATH` auf
eine passende Playwright-Moduldatei setzen, dann
`node scripts/rent_payment_browser_qa.mjs`. Der Test legt ausdrücklich synthetische
Datensätze an und setzt eine dafür bestimmte Testinstanz voraus. Die lokalen
Ergebnisse liegen unter `artifacts/continuation-20261013/rent-browser/`.

Der abschließende XStress-Kurzlauf mit 15 Einheiten, 27 Mietverhältnissen und einem
simulierten Jahr führte **2.158 API-Aufrufe** aus. Fachliche Fehler, kritische
Fehler, erkannte Funktionslücken und Berechtigungsfehler: jeweils **null**. Er prüfte
auch Export/Import, Sicherung/Wiederherstellung, Migration und harten Prozessabbruch.
Im gemischten Zugriff mit zehn getrennten Benutzern: 456 Anfragen in 30,6 Sekunden,
40 von 40 bestätigten Schreibvorgängen anschließend geprüft, 79 tatsächliche
Lese-/Schreibüberlappungen, p95 1,04 Sekunden und keine Fehler.

**Dieser XStress-Lauf ist insgesamt nicht grün:** Zwei Anfragen beim gleichzeitigen
Schreibstoß benötigten 2,3 beziehungsweise 2,4 Sekunden und überschritten die
unveränderte Zwei-Sekunden-Grenze. Der Prozess liefert deshalb korrekt Exitcode 1.
Der Bericht unter `artifacts/continuation-20261013/xstress/run-wm4hmd06/` hält diese
beiden Leistungsbefunde und sechs Hinweise fest. Der XStress-eigene UI-Lauf wurde
ausgelassen und durch den beschriebenen gezielten echten Browserlauf ergänzt.
Ein vollständiger Fünfjahreslauf mit 120 Einheiten ist damit nicht nachgewiesen.

### Nächste klar abgegrenzte Arbeiten

1. Die verbleibende Latenz im Großbestand messen: SQL-Laufzeit, Wartezeit auf die
   globale Anwendungssperre, Cache-Treffer und Invalidierungen getrennt erfassen.
   Der lesend geprüfte SQLite-Abfrageplan zeigt beim reinen Datumsfilter einen
   Buchungsvollscan; ein Datumsindex ist ein gezielt zu messender Kandidat.
2. Cashflow-Abfragen erhalten die globale Sperre bereits vor dem Cache-Lookup.
   Einen nach Filter und Zugriffsbereich getrennten Berechnungsschutz erst nach
   Messung und Regressionen für sofortige Aktualität/Portfolioisolation umstellen.
3. Dieselbe Großbestandsmessung unter PostgreSQL durchführen. Die jetzigen echten
   PostgreSQL-Parallelitätstests belegen Wiederholungssicherheit, keine dortige
   Millionendatensatz-Leistungsgrenze.
4. Die zwei langsamen Schreibzugriffe gesondert untersuchen; die Messgrenze bleibt
   erhalten. Externe WISO-/TEHA-Abnahmen und die übrigen Fachpakete bleiben offen.

Der Push dieses Pakets aktualisiert den Entwicklungszweig. Die Anwenderinstallation
wird dadurch weder migriert noch automatisch ausgetauscht. Der Test-PostgreSQL-
Server wurde nach den Prüfungen wieder beendet.

Abschließende statische Gesamtprüfung: Ruff bestanden; mypy prüft alle 370
Backend-/Prüfdateien erfolgreich. Die dabei zuerst gefundenen Typfehler in drei
neuen Testdateien wurden korrigiert und deren 17 Such- beziehungsweise 26
Mietzahlungsfälle erneut erfolgreich ausgeführt. Der Produktcode blieb dabei
unverändert. Der vorangegangene vollständige Backend-Gesamtlauf wird für dieses
Paket nicht erneut behauptet; maßgeblich sind die oben getrennt aufgeführten
gezielten Regressionen, echten Datenbank-/Browserprüfungen und Lastläufe.

## Zweites Paket: Cache-Richtigkeit, Transaktionen und verbleibende Last

Ausgangspunkt ist der veröffentlichte Stand `3909602b`. Der nächste Schritt folgt
den tatsächlich verbliebenen Messbefunden und erweitert die Prüfung um deren
Richtigkeitsrisiken. Die Ausgangsläufe bleiben unverändert erhalten.

- **Datumsindex:** explizite Migration `7a2c8e4f1b90`, gleicher ORM-Index für neue
  Datenbanken. SQLite und PostgreSQL verwenden ihn im geprüften selektiven
  Zeitraumbericht, bei unveränderten Summen und vollständig erhaltenen Daten.
  Upgrade/Downgrade und Startverweigerung eines alten Schemas wurden geprüft.
  Die PostgreSQL-Prüfung liegt in einer eigenen, vom verpflichtenden CI-Gate
  automatisch erfassten Datei. Details: `BOOKING_DATE_INDEX_20261013.md`.
- **CSV:** gemeinsamer Feldschutz für normale Berichte und Suche sowie die
  Tabellenexporte im Frontend. Auch Texte mit führenden Leerzeichen werden als
  Text behandelt. Echte negative Zahlen bleiben Zahlen; Kommas, Anführungszeichen
  und CR-/LF-Zeilenumbrüche werden korrekt serialisiert. Proprietäre DATEV-/WISO-
  Formate werden damit nicht verändert. 42 gezielte Backendfälle unter Memory und
  dieselben 42 unter SQLite sowie 28 gezielte Frontendfälle bestanden.
- **Mobile Mietübersicht:** kompakte Kennzahlen, bei langen Beträgen automatisch
  breitere Karten und eine aufklappbare Erklärung der Berechnungsgrundlage.
  Der echte Browserlauf besteht sieben Abläufe bei 1440/360/320 Pixeln,
  einschließlich einer ausdrücklich nur zur Layoutprüfung simulierten großen
  Summe. Kontrollbilder wurden visuell geprüft. Der vorhandene Zahlungsablauf
  einschließlich verlorener Antwort und Nur-Lese-Rolle besteht weiterhin.
- **Cache:** Datenbankidentität, Zugriffsgrenze und normalisierte Argumente trennen
  Einträge. Ergebnisse werden gegen unbeabsichtigte Mutation geschützt. Unbestätigte
  Änderungen, feste Lesesnapshots und Savepoints dürfen keine fremden Cacheeinträge
  lesen oder veröffentlichen. ORM-, Core-/Text- und Bulk-Änderungen invalidieren
  auch nach Abschluss der äußeren Transaktion. Ein Cachetreffer muss nicht hinter
  einer fremden langsamen Berechnung warten. Nachweise: 42 gezielte SQL-Regressionen,
  vier echte PostgreSQL-Isolationstests, ein tatsächlicher authentifizierter HTTP-
  Cachetreffer; nach Typkorrekturen nochmals 26 gezielte SQL-Cachetests.
- **Atomare normale Buchungen:** POST, Storno, PUT und PATCH speichern Buchung und
  automatische Zuordnungen gemeinsam. Ein Fehler rollt auch bereits angelegte
  Zuordnungen zurück. Gemessen wird je Vorgang ein fachlicher Commit; Audit bleibt
  separat. Eigene verschachtelte Vorgänge nutzen Savepoints und hängen am äußeren
  Commit. Fremde ungeflushte Änderungen des Aufrufers bleiben erhalten. Eine bereits
  physisch aktive fremde SQLite-Transaktion muss vor einem unabhängigen Schreibvorgang
  beendet werden; sie wird weder heimlich mitcommitted noch zurückgerollt.
  38 Unitprüfungen, sechs native PostgreSQL-Prüfungen und 41 SQL-HTTP-Regressionen
  bestanden; backendabhängige Skips wurden getrennt aufgezeichnet.

Die unabhängige Prüfung der neuen atomaren Vorgänge deckte drei zusätzliche
Richtigkeitsfälle auf und führte jeweils zu einer Regression:

1. Der Memory-Änderungsjournal muss weiterhin durch die Objektberechtigungen
   laufen. Bekannte fremde Buchungskennungen dürfen auch innerhalb eines Journals
   keine Bearbeitung oder Stornierung ermöglichen. Rollback kopiert nur geänderte
   Einträge, keinen vollständigen historischen Bestand.
2. Referenzeltern werden in PostgreSQL in konsistenter Reihenfolge gesperrt und
   ihre Zuordnung nach Wartezeiten erneut geprüft. Ein Portfoliowechsel wartet
   bis zum Buchungsabschluss. Der Mieter wird vor Ermittlung der Vertragskandidaten
   gesperrt, damit ein parallel eingefügter Vertrag keine ungeschützte neue
   Zuordnungsgrundlage bildet.
3. Eigene verschachtelte SQL-Vorgänge dürfen nicht unabhängig committen. Scheitert
   der äußere Vorgang, verschwinden auch seine inneren Buchungen. Ein abgefangener
   innerer Fehler rollt seinen Savepoint zurück und lässt den übrigen äußeren
   Vorgang konsistent fortfahren.

Der gesamte Frontendlauf bestand 353 Tests. Nach der letzten Ergänzung des CSV-
Feldschutzes um Steuerzeichen/BOM bestanden nochmals 22 gezielte CSV-/Tabellentests
und 14 Backend-CSV-Tests. Gesamter Frontend-Lint und Produktionsbuild bestanden;
Ruff und mypy prüfen den Backendstand mit 380 Dateien erfolgreich.

Die vertiefte Untersuchung korrigiert außerdem die Lastbeschreibung: Der frühere
Schreibstoß bestand aus 40 Zahlungen mit höchstens **acht gleichzeitig laufenden
Anfragen**. Die zwei langsamen Anfragen benötigten im inneren Servertimer jeweils
2,125 Sekunden; allein der HTTP-Client erklärt die Verzögerung daher nicht.
Buchung, Zuordnung und Audit verursachten bisher ungefähr drei Commitzyklen pro
Zahlung. Der globale Berechnungslock gehört nicht zum Buchungs-Endpunkt.

Neue lokale Laufartefakte dieses Pakets liegen unter
`artifacts/performance-20261013/`; die vorherigen Großbestandsläufe bleiben unter
ihren bisherigen eindeutigen Verzeichnissen bestehen.

### Neuer Millionentest auf `8c9686cd`

`rows-1000000-v1v0dtl1` bestand alle ausgeführten fachlichen Orakel, Suchseiten,
vollständigen Exporte und Nachprüfungen. Zehn getrennte Benutzer erreichten zehn
gleichzeitige Anfragen; **40 von 40** bestätigten Schreibvorgängen wurden einzeln
nachgeprüft, mit 91 Lese-/Schreibüberlappungen und ohne HTTP-Fehler. Die relevanten
Quellfingerprints blieben während des Laufs unverändert; eigene Prozesse wurden
nachweislich beendet. Lastfenster: 60 Sekunden, mit Abschluss laufender Anfragen
62,77 Sekunden. Vergleich: vorheriger erfolgreicher Lauf
`rows-1000000-km9ecxc7`, ebenfalls 60 Sekunden konfigurierte Last.

| Route / Messung | Vorher | Neues Paket |
| --- | ---: | ---: |
| Cashflow unter Mischlast: Anfragen | 32 | 903 |
| Cashflow unter Mischlast: p95 / Maximum | 9,119 / 9,176 s | 0,768 / 1,448 s |
| Suche unter Mischlast: Anfragen | 52 | 64 |
| Suche unter Mischlast: p95 / Maximum | 6,288 / 6,496 s | 4,905 / 5,149 s |
| Schreibzugriffe unter Mischlast: Maximum | 0,359 s | 0,563 s |
| Finanzbericht ohne Mischlast: Maximum | 2,068 s | 2,174 s |
| Cashflow ohne Mischlast: Maximum | 2,861 s | 3,499 s |

Die Verbesserung betrifft vor allem wiederholte historische Finanzabfragen im
Parallelbetrieb. Nicht alle Messwerte werden schneller: der breiteste Cashflow-
Einzelaufruf und die maximale Schreibzeit liegen höher. Die gesamte Messung
einschließlich Neuerzeugung des indexierten Bestands dauerte 221,42 statt 186,50
Sekunden. Das neue Paket ist daher kein pauschaler Geschwindigkeitsgewinn für
beliebige Abfragen oder Importe. Die verbleibenden rund fünf Sekunden Suchlatenz
unter Mischlast erfordern einen eigenen weiteren Arbeitsschritt.

Rohwerte und der reproduzierbare Routenvergleich liegen unter
`artifacts/performance-20261013/scale-comparison.json`. Die fachlichen und
systemischen Ausschlüsse des bisherigen Benchmarks gelten weiterhin, besonders
für PostgreSQL-Leistung, globale Prüfliste, physische Dokumentarchive und eine
vollständige 20-Jahres-Simulation.

### Gegenprobe zum Schreibstoß und weiterer Korrekturschritt

Der anschließende vollständige XStress-Kurzlauf auf `8c9686cd` bestätigte erneut
korrekte Fachwerte, Berechtigungen und 40 von 40 nachgelesenen Lastzahlungen.
Er war dennoch **nicht grün**: Sechs gleichzeitige Buchungsanfragen überschritten
die unveränderte Zwei-Sekunden-Grenze, maximal 4,5 Sekunden. Originalnachweis:
`artifacts/performance-20261013/xstress/run-rui27ve6/`.

Die inneren Servertimings zeigen, dass spät gestartete Schreibanfragen früher
beendet wurden als lange wartende Anfragen. Das stützt die Diagnose konkurrierender
SQLite-Schreiber, ersetzt jedoch keine getrennte Messung von Queue, Verbindungs-
erwerb, BEGIN und Commit. Diese Zeitabschnitte werden deshalb im nächsten Lauf
mit der jeweiligen Anfragekennung protokolliert. XStress schreibt nun einen
fortlaufenden `requests.jsonl`-Nachweis ohne Nutzdaten, Zugangsdaten oder
Antwortinhalte; 18 Werkzeugregressionen bestanden einschließlich dieses Schutzes.

Zusätzlich halten die bisherigen Plausibilitätsprüfungen eine Request-Leseverbindung,
während die Fachunit eine eigene Verbindung anfordert. Bei sehr vielen gleichzeitigen
Schreibern kann das den Verbindungspool gegenseitig blockieren. Die Korrektur darf
ausschließlich nachweislich saubere, automatisch begonnene Request-Lesetransaktionen
freigeben; fremde, explizite oder noch unbestätigte Schreibtransaktionen bleiben
erhalten. Die bisherige Regression wird durch die erfolgreiche Cashflow-Messung
nicht verdeckt.

### Geordnete Schreiber und sichere Verbindungsfreigabe

Implementierungsstand `5cb201f0` enthält eine FIFO-Warteschlange je SQLite-Engine
für Buchungs-, Dokumentarchiv- und Auditschreibvorgänge. Die Zulassung erfolgt vor
dem Verbindungserwerb und gilt bis zum Transaktionsende. PostgreSQL nutzt seine
eigenen Sperren. Externe Prozesse und bislang nicht umgestellte Legacy-, Billing-
und Maintenance-Schreiber werden durch diese prozesslokale Queue nicht geordnet.
Die Queue darf deshalb nicht als globale Serialisierung sämtlicher Datenbank-
zugriffe ausgegeben werden. Queuewartezeit, Verbindungserwerb, BEGIN, Commit oder
Rollback und Haltezeit sind mit Anfragekennung getrennt messbar. Im Audit wird
die Kennung ausdrücklich über die äußere Middleware weitergegeben und danach
zurückgesetzt; SQL, Nutzdaten und Zugangsdaten gelangen nicht in diese Zeitlogs.

Eine eigene Fachtransaktion darf vorher ausschließlich eine nachgewiesene reine
AUTOBEGIN-Lesetransaktion der registrierten Request-Session zurückgeben. Fremde
Sessions, Connection-Binds, explizite Transaktionen, ausstehende Änderungen,
Savepoints und feste Snapshots werden erhalten. Connection-Level-Tracking erkennt
auch direkte SQLAlchemy-Connection-Schreibzugriffe, DML-CTEs, unbekanntes SQL,
Funktionsaufrufe und Locking-Selects. SQLite verlangt zusätzlich eine nachweislich
nicht aktive physische Transaktion. PostgreSQL prüft im selben diagnostischen
Roundtrip die serverseitige XID und eigene gewährte Advisory-/Relationlocks
außerhalb von AccessShare. Die XID-Abfrage vergibt selbst keine neue XID.
[PostgreSQL 16: Transaktionsinformationen](https://www.postgresql.org/docs/16/functions-info.html),
[Sperrübersicht](https://www.postgresql.org/docs/16/view-pg-locks.html).

Rohe DBAPI-`BEGIN`-/`SET`-Steuerung liegt ausdrücklich außerhalb dieses disponiblen
Middleware-Lesevertrags; dafür bleiben `Session.begin()` beziehungsweise eine
caller-eigene Connection der geschützte Weg. Die Fachunit wiederholt unmittelbar
vor ihrer Speicherung die maßgeblichen Berechtigungs- und Zuordnungsprüfungen.

Abnahme vor den Endmessungen: acht Queue-/Audit-/Kontextprüfungen, 22 SQLite-
Verbindungs-/Transaktionsprüfungen, sechs PostgreSQL-Buchungsprüfungen und 13 native
PostgreSQL-Helperprüfungen bestanden. Der deterministische Pool-Kontrollfall mit
zwei Verbindungen und zwei Request-Schreibern lässt ohne Readfreigabe beide
Schreiber in den Pooltimeout laufen; mit Freigabe committen beide. Echte PostgreSQL-
Prüfungen belegen außerdem den Erhalt roher DBAPI-Schreibänderungen und zusätzlicher
Caller-Sperren. Eine unabhängige rein lesende Endprüfung des Commits hat keinen
weiteren konkreten Befund. Globale Ruff-Prüfung und mypy mit 383 Dateien bestanden.
Die Endmessungen und Gesamtregression werden anschließend ergänzt.

### Verbliebene Großbestandspfade

Eine weitere rein lesende Prüfung bestätigt als nächsten wesentlichen Engpass die
globale Prüfliste: Sie lädt weiterhin alle Buchungen samt Zuordnungen/Kautionslinks
und bildet zusätzliche Vollbestandsstrukturen. Der abgesicherte Volltabellen-Cache
kopiert diese Modelle tief; die bisherige Millionentest-Abnahme schließt diesen
Pfad ausdrücklich aus. Geplant ist eine gemeinsame SQL-Prüfgrundlage mit genauen
Zählern, Cursorseiten und vollständigem Export. Legacy-Zahlungen ohne gespeicherte
Zuordnung benötigen dabei einen begrenzten, fortsetzbaren Fallback nach denselben
Fachregeln. Einzelne Kautionslinks bleiben vor der Summierung centgenau gerundet.

Das Dashboard verwendet keine vollständige Buchungsliste, liest jedoch zahlreiche
andere Tabellen vollständig. Die globale Dokumentenseite sammelt noch alle API-Seiten,
während die Mieter-Dokumentansicht bereits tatsächlich paginiert ist. Diese konkreten
Unterschiede werden im nächsten Paket berücksichtigt; historische bereits behobene
Lücken werden nicht erneut als offen ausgewiesen.
