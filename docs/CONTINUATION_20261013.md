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
