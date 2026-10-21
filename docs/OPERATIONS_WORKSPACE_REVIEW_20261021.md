# Aufgaben, Kalender und Projektakten – Prüfung vom 21.10.2026

Fortsetzung auf dem geprüften Integrationsstand `06d5b6f1`, einschließlich Claudes
Arbeiten bis `ebcd4348`. Schwerpunkt sind tägliche Bedienung und nachvollziehbare
Bezüge; WISO und TEHA bleiben entsprechend der späteren Priorisierung zurückgestellt.

## Behobene Ursachen

1. **Beendete Aufgabenserien:** Der manuelle Generator und der dauerhafte Job
   berücksichtigten abgebrochene und archivierte Ausgangsaufgaben weiterhin.
   Beide verwenden jetzt dieselbe Entscheidung. Eine erledigte Ausgangsaufgabe
   bleibt eine aktive Serie; eine abgebrochene oder archivierte Serie erzeugt
   keine weiteren Aufgaben. Bereits angelegte Kinder bleiben erhalten.
2. **Aufgabenbezüge:** Neue Elternverweise müssen erreichbar sein und dürfen
   keinen Kreis bilden. Leere Titel werden beim Schreiben abgelehnt, historische
   Daten bleiben lesbar. Ein Ausgangspunkt mit bestehenden Folgeaufgaben kann
   über die normale Aufgabenverwaltung nicht gelöscht werden; die Fehlermeldung
   verweist auf das Beenden der Serie.
3. **Schadenakten:** Die Einheit muss tatsächlich zur Immobilie gehören. Die
   Zuordnung wird innerhalb derselben Transaktion gesperrt und geprüft.
   Beim zulässigen Objektwechsel ziehen verknüpfte Kalendertermine atomar mit.
   Rechnungen und finale Protokolle verhindern weiterhin einen Objektwechsel.
4. **Projektworkflow:** Auch alte Abschlusswerte `done` und `closed` müssen offene
   Arbeitspakete berücksichtigen. Die ursprünglichen Statuswerte und die Chronik
   bleiben kompatibel. Negative Budgets und leere Titel werden abgelehnt.
5. **Kalender und Projekttermine:** Direkte Kalenderänderungen benötigen auch die
   Schreibrechte der Projektakte und respektieren deren Abschluss. Ein Termin
   kann nicht unabhängig von seiner Projektakte auf ein anderes Objekt versetzt
   werden. Das Löschen erfolgt mit denselben Kaskaden im Speicher- und SQL-Betrieb.
6. **Kalenderdaten:** Objekt-, Einheits-, Projekt- und Datumsfilter werden vor der
   Seitenauswahl ausgewertet. SQL lädt nur die angeforderte Seite. Die Reihenfolge
   ist Datum, Uhrzeit und eindeutige ID. Die Antworten enthalten den zugehörigen
   Projekt- und Terminbezug; Bestandsdaten benötigen dafür keine neue Spalte.
7. **Bearbeitung und Übersicht:** Schadenformulare begrenzen die Einheiten auf die
   Immobilie und entfernen nach einem Objektwechsel die vorige Auswahl. Termine
   erhalten Datum und Uhrzeit. Unveränderte Werte bleiben exakt erhalten; neue
   Eingaben verwenden die lokale Uhrzeit der bestehenden zeitzonenlosen Spalte.
   Ein UTC-Export in dieses Feld würde beim SQL-Rundlauf die Uhrzeit verschieben.
8. **Gemeinsame Zustände:** Projekt- und Kalenderänderungen aktualisieren auch die
   verknüpften Ansichten. Abgebrochene Anfragen überschreiben keine neuere
   Darstellung. Projektaktionen besitzen einen sofort wirksamen Doppelklickschutz.

## Bedienwege

- Aufgaben und Termine haben eine lesbare Detailansicht mit Beschreibung,
  Zuständigkeit beziehungsweise Teilnehmern und Links zu ihren Quellen.
- Objektbezüge bleiben oberhalb der Liste sichtbar, führen zurück in die Akte
  und können gezielt aufgehoben werden. Neue Datensätze übernehmen diesen Bezug.
- Aufgaben, die historisch nur eine Einheit enthalten, erscheinen auch in der
  Auswahl ihrer Immobilie. Abgebrochene Aufgaben lassen sich ausdrücklich
  wieder öffnen; aktive Serien lassen sich mit Erklärung beenden.
- Kalendertermine lassen sich über einen freien Zeitraum, heute oder die nächsten
  30 Kalendertage auswählen. Projekttermine führen direkt zum Terminreiter der
  richtigen Akte; einzelne Termine sind aus der Akte direkt im Kalender erreichbar.
- Die Projektübersicht verlinkt Immobilie, Einheit und Handwerkerkontakt. Der
  Kopfbereich führt zu den Terminen und den Aufgaben des betroffenen Objekts.
- Fehler beim Laden von Objektauswahlen erscheinen mit Wiederholen-Aktion.
  Unvollständig geladene Auswahlen öffnen kein scheinbar vollständiges Formular.

## Regressionen und Abnahme

Die neuen Gegenbeispiele wurden zuerst gegen den unveränderten Code ausgeführt:
15 Testfälle scheiterten wie erwartet. Abgedeckt werden anschließend Speicher und
SQLite, der dauerhafte Nachholjob, Legacy-Kompatibilität, fehlgeschlagene Änderungen
ohne Teilübernahme, Rollen, Zeitangaben und Filter nach über 1.000 anderen Terminen.
Der PostgreSQL-Pflichttest prüft dieselben Objekt-/Kalenderbezüge aus unabhängigen
Sitzungen. Übersprungene PostgreSQL-Prüfungen gelten nicht als Freigabe.

`scripts/operations_browser_qa.mjs` führt auf ausschließlich synthetischen Daten
die wirklichen Formulare und Akten durch: Anlegen aus einer Einheit, Serienende,
unveränderte und geänderte Uhrzeit, Projekt-/Kalenderrundlauf, Objektkorrektur,
Datumsfilter und sämtliche Projektreiter bei 320, 360 und 1440 Pixeln. Der Aufruf
erfolgt mit `scripts/run_daily_browser_qa.py --suite operations`; die Suite gehört
auch zur CI. Daneben bleiben die vollständige Frontend- und Backend-Suite sowie
der gemeinsame Browserlauf aller Anwendungsseiten verpflichtend.

Die Auslieferung erfolgt erst nach grüner CI des konkreten Commits, Prüfung des
Windows-Builds, Vollbackup und isolierter Wiederherstellung. Die privaten Nachweise
dieser Runde liegen unter `Documents/ImmoManager-Sicherungen/20261021-Betriebsablaeufe`.
Sie dokumentieren den endgültigen Commit, die Testzahlen und die tatsächliche
Umstellung. Diese Datei erklärt den Codeumfang und ersetzt diese Freigabe nicht.
