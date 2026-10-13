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
