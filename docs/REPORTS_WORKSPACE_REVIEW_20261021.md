# Auswertungen, Statistiken und Berichte

Prüfrunde vom 21. Oktober 2026 auf dem ausgelieferten Stand
`07aa735a54287b92a941dad5311875cddd1f2919`. Claudes zuletzt abgerufener Commit
`ebcd434840b19f9ab7a940eaea02c5a8d40bdacc` ist enthalten. Seine Oberflächen und
Fachabläufe bleiben die Grundlage. PR #37, Hauptbranch und Release-Tags werden
in dieser Runde nicht zusammengeführt oder verändert.

## Rechenfehler und überprüfbare Gegenbeispiele

| Befund | Nachweis | Korrektur |
| --- | --- | --- |
| Eine künftige Mietzahlung kürzt nur die Erwartung ihres Buchungsmonats. | Drei Monatsmieten zu je 100 EUR, Anfangssaldo 1.000 EUR, eine geplante Vorauszahlung von 300 EUR im Februar: Die Prognose zeigt 1.400 statt 1.300 EUR; bei Buchung im Januar sogar 1.500 EUR. | Künftige, im Bericht enthaltene Zahlungen reservieren die Ansprüche über das vollständige FIFO-Mietkonto. Annahmen über Zahlungsausfälle gelten auf die danach verbleibenden Ansprüche. Rückzahlungen werden im selben Konto berücksichtigt. |
| Eine stornierte Rechnung fließt in das Periodenergebnis ein. | Stornierte Rechnung über 400 EUR erzeugt 400 EUR Aufwand. | Stornierte Rechnungen liefern keinen Leistungsaufwand. Tatsächliche Buchungen behalten ihre eigene Zahlungsidentität. |
| Bei einem einzelnen Mieter ignoriert die gemeinsame Zahlungslesefunktion eine bereits ausgewählte Buchungsliste. | Der Einzelmieterpfad liest die Buchungen erneut und verwirft so die Auswahl des Aufrufers. | Vorab ausgewählte Buchungen werden auch für genau einen Mieter verwendet. |
| Saldenkarten führen zu falschen Quellen. | Anfangssaldo und Basisprognose öffnen dieselbe Liste künftiger Szenariozahlungen. | Getrennte Quellen für Kontovortrag/bisherige Buchungen, künftiges Szenario und künftige Basisprognose. Jede Liste lässt sich mit ihrer Kennzahl abstimmen. |
| Unvollständige Gesamtsummen werden wie Nullwerte dargestellt. | Formal vorhandene Monatsliste bei fehlenden oder leeren Gesamtbeträgen. | Fehlende numerische Nachweise erzeugen einen wiederholbaren Ladefehler; kein erfolgreicher Nullbericht und kein Download. |
| Kategoriestatistik verliert Vorzeichen und Vollständigkeit. | Absolute Kreiswerte; Kategorien und Kostenschätzungen nach Position acht fehlen. | Vollständige Listen mit Vorzeichen und passenden Buchungslinks. Buchungen ohne Kategorie bleiben erreichbar. |
| Fremdwährung wird in Ergebnis und Planung als Bestandswährung dargestellt. | Eine Buchung vom USD-Konto zu einem EUR-Objekt wird ohne Portfoliowahl in EUR summiert. | Alle drei Berichtsbasisarten prüfen die tatsächlichen Quellkontowährungen; unprüfbare oder gemischte Beträge werden nicht still umgerechnet. |
| Teilrückbuchungen erzeugen Centbruchteile in den Leistungsquellen. | 30 EUR Auszahlung, davon 10 EUR einer Rechnung zugeordnet, und 1 EUR Rückbuchung: Quellen ergeben 29,333… statt der angezeigten 29,33 EUR. | Die anteilige Zuordnung wird an der Beleggrenze auf Cent gerundet; Quellen, Monatswerte und Gesamtsummen stimmen exakt überein. |
| Die Projektakte überschreitet im Zweibenutzerlauf wiederholt zwei Sekunden. | Profilierung: Statushistorie etwa 425 ms und Fotos etwa 232 ms, weil für einen ausdrücklich gewählten Schaden trotzdem sämtliche polymorphen Objektfamilien in die SQL-Prüfung expandieren. | Historie und Fotos verwenden den bekannten Schadenstyp und eine im selben SELECT enthaltene vollständige Objektberechtigung. Fremde Schäden und andere Typen bleiben ausgeschlossen; unabhängige Rechnungs-/Dokumentquellen behalten ihre eigenen Prüfungen. |

Geld bleibt in den Berechnungen dezimalgenau. Bekannte künftige Buchungen sind
Reservierungen und werden in der Vorschau nicht als bereits bezahlte Istwerte
umgebucht. Die Report-Erstellung verändert weder Mietkonten noch Quelldatensätze.

## Darstellung und Exporte

- Quellenwahl für Anfangssaldo, Basis und Szenario; ein Kennzahlklick entfernt
  alte Suchfilter, damit sie den angeforderten Nachweis nicht unsichtbar machen.
- Kontovorträge öffnen das konkrete Konto, Rechnungswarnungen die betroffene
  Rechnung; Vertrags- und Buchungsnachweise erhalten ihre genauen Datensatzlinks.
- Sichtbarer Berichtszeitraum, Datumsformatierung und klare Erläuterung der Salden.
- Vollständige Zahlungsquellen bleiben auch nach Position 100 seitenweise erreichbar.
- CSV enthält Gesamtsummen, Anfangs-/Endsaldo und alle drei Quellenarten.
  Vertrauenswürdige Dezimalbeträge bleiben numerisch, auch mit negativem Vorzeichen;
  freie Texte behalten den vorhandenen Schutz gegen Tabellenformeln.
- PDF zeigt benannte Immobilien-/Einheitenauswahl, deutsch formatierte Beträge mit
  tatsächlicher Währung, Gesamtsummen, lesbare Quellen und den Berechnungsnachweis.
- Das Dashboard unterscheidet seine historische Durchschnittsfortschreibung von
  der detaillierten Liquiditätsplanung und bietet einen direkten Wechsel. Geschätzte
  Instandhaltungskosten werden ausdrücklich als Schätzungen bezeichnet.

## Abnahme und Auslieferung

Neue numerische Regressionen: `backend/tests/test_report_source_reconciliation.py`.
`test_project_source_reading.py` prüft die Projektquellen samt Typ-, Eltern- und
Portfoliogrenze sowie die begrenzte SQL-Abfragekomplexität ohne flüchtige Zeitgrenze.
Sie gehören zusätzlich zu den vollständigen Backend-Suiten auch zur verpflichtenden
echten PostgreSQL-Prüfung zusammen mit den bisherigen Finanzgegenbeispielen.
`FinanceWorkspace.test.jsx` und `DashboardWorkspace.test.jsx` prüfen die Bedienung.
Die bestehende Zwischenablage-Fehlerprüfung wartet ausdrücklich auf den gestarteten
Schreibversuch und die asynchrone Fehlermeldung; eine noch ausstehende React-Aktualisierung
wird nicht mehr als verschwundener Fehler gewertet. Erfolgs- und Fehlerbedingungen bleiben erhalten.

`scripts/run_daily_browser_qa.py --suite reports` prüft ausschließlich auf einem
eigenen synthetischen Server: Zahlungssummen und übernommene Buchungsfilter,
Vertragsquellen, stornierte Rechnungen, mehrmonatige Vorauszahlung, Kontonachweis,
getrennte Basis-/Szenarioquellen, tatsächliche JSON-/CSV-/PDF-Downloads und eine
unvollständige Antwort mit anschließender Wiederholung und den Weg von der
Dashboard-Kategoriestatistik zu den Buchungen. Fünf Ansichten werden
bei 320, 360 und 1440 Pixeln geprüft. Externe Browseranfragen sind gesperrt.

Zur Freigabe gehören die vollständige CI für genau den Commit, die vorhandenen
Windows-Abnahmesuiten plus neue Berichtssuite, eine neue Vollsicherung und deren
tatsächliche isolierte Wiederherstellung mit dem gebauten Windows-Programm.
Vor Umschaltung werden Originale, geschützte Kontodateien und fachliche Tabellen
erneut mit der getesteten Sicherung verglichen. Normalstart und expliziter
Schema-Upgrade bleiben getrennt; diese Runde benötigt keine neue Migration.

Der endgültige Nachweis samt Paketprüfsumme, CI, Sicherungen, Browserbildern und
Wiederherstellungsprotokoll liegt unter
`C:/Users/matth/Documents/ImmoManager-Sicherungen/20261021-Auswertungen-Berichte`.
WISO-/TEHA-Schreibübertragungen und echter Nachrichtenversand gehören nicht zu
dieser Prüfrunde. Bekannte historische Zahlungskennzeichen ohne Beleg werden
nicht als belegte Zahlung ergänzt.

## Zusätzliche Gegenprüfung datierter Zahlungen

Die abschließende Gegenprobe hielt den Kandidaten `47e28de9` vor der Auslieferung
zurück: Forderung 100, datierte Teilzahlung 40 und Anfangssaldo 1.000 ergaben
1.140 statt 1.100. Die Prognose verwendet jetzt den kanonischen Rest zum Ende
ihres Planungshorizonts. Teilzahlungen, Rückbuchungen, Guthabenverrechnung,
Lieferantengutschriften und tatsächlich erworbenes Skonto reduzieren genau
die verbleibende Erwartung; Zahlungen außerhalb des Horizonts bleiben außen vor.

Unverrechnete Vertragsabschläge berücksichtigen den wirksamen Zahlungsanteil
nach Rückbuchungen, auch bei Vorauszahlung im laufenden Monat. Der Anteil wird
nach den Vertragsorten verteilt, damit Objektberichte zum Gesamtbestand passen.
Einzelne Erstattungen ersetzen keine weitere erwartete Abschlagszahlung. Ohne
Rechnungsperiode gilt der Buchungsmonat; diese Annahme steht im Bericht.

Auch eine ausdrücklich auf null gesetzte Szenarioquelle ersetzt weiterhin die
automatische Erwartung. Zahlungskennzeichen ohne ausreichenden Nachweis erzeugen
verlinkte Hinweise. Zunächst werden fünf angezeigt, sämtliche weiteren lassen
sich aufklappen. Forderungsquellen öffnen die konkrete Forderung.

`test_forecast_payment_horizon.py` hält 22 Fälle für beide lokalen Speicherarten
und die verpflichtende PostgreSQL-Prüfung fest. Vor der Korrektur schlugen 17
der ersten 21 Gegenproben fehl; die zugehörigen Belege bleiben im privaten
Freigabeverzeichnis erhalten. Eine genehmigte Lieferantengutschrift reduziert
auch eine ältere Rechnung ohne angelegte Prüfakte, in Prognose und Periodenkosten.

## Folgebearbeitung während einer laufenden Listenaktualisierung

Die abschließende Büroprüfung zeigte bei zwei unmittelbar aufeinanderfolgenden
Aufgabenänderungen einen falschen Versionskonflikt. Nach dem ersten Speichern
verwendete die Arbeitszentrale vorübergehend die alte Listenrevision, obwohl der
neue Datensatz bereits bestätigt war. Der Server wies den veralteten zweiten
Aufruf korrekt zurück und erhielt die Eingabe.

Speichern und Rückgängig übernehmen jetzt sofort den bestätigten Datensatz samt
Revision. Der gemeinsame Listendienst bricht überholte Lesevorgänge unmittelbar
ab, bevor er die neue Abfrage startet. Eine Regression verzögert diese Abfragen
absichtlich, bearbeitet mehrere Felder, nimmt eine Änderung zurück und liefert
danach noch eine alte Antwort aus. Jede Folgeänderung muss die jüngste bestätigte
Revision verwenden. Die ursprüngliche fehlgeschlagene Windows-Prüfung bleibt
als Nachweis erhalten; Prüfungen und Konfliktschutz werden nicht abgeschwächt.
