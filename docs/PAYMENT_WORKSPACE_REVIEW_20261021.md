# Bankimport, Zahlungszuordnung, Mahnwesen und Kautionen – Prüfung 21.10.2026

Ausgangspunkt: `b89588fccd53ec04bafdf4c738ed69445afcfab1`, einschließlich Claudes veröffentlichter Arbeiten bis `ebcd434840b19f9ab7a940eaea02c5a8d40bdacc`. Vorhandene Akten, Dokumentoriginale, Rollen, Formularschutz und Fachabläufe werden weitergeführt. Keine Änderungen an der Datenbankstruktur.

## Korrigierte Gegenbeispiele

* 1.200 EUR Eingang mit 700 EUR Miete und 500 EUR Kaution plus weiterer Kautionszahlung von 1.000 EUR: Eine vollständige Rückbuchung des ersten Eingangs durfte bisher 1.200 EUR Kaution korrigieren. Jetzt höchstens dessen eigene 500 EUR; der Mietrücklauf beträgt 700 EUR. Mehrere Rückbuchungen teilen denselben verbleibenden Originalanteil.
* Eine noch nicht zugeordnete Rückbuchung kann das tatsächlich verbleibende Geld unter den erfassten Kautionsbestand senken. Die Akte zeigt einen verlinkten Prüfhinweis; eine endgültige Abrechnung wird bis zur Klärung gesperrt. Historische Originale werden nicht verändert.
* Ohne festes Kautionskonto konnten Buchungen derselben Partei aus einem anderen Portfolio verwendet werden. Kandidatenauswahl und Speicherung prüfen jetzt das Vertragsportfolio.
* Kautionskandidaten waren nach 200 Treffern abgeschnitten. Vollständige Abschnitte und Suche nach Text, ISO-Datum oder Betrag erschließen den gesamten passenden Bestand.
* Scheiterte eine ältere manuelle Zahlungsaufteilung nach dem ersten Teilbetrag, konnten vorherige Zuordnungen bereits entfernt sein. Der Kompatibilitätspfad schreibt jetzt atomar.
* Ein bereits belegter Forderungsanteil fehlte im angezeigten Bankbudget und dessen Änderung in der Vorschau-Revision. Beides wird berücksichtigt; veraltete Vorschläge erhalten einen Konflikt.
* Die Buchungsliste zeigte vollständig für Kaution/Forderung verwendete Beträge als unzugeordnete Miete. Sie rechnet Reservierungen jetzt centgenau ab.
* Der Aufteilungsdialog lädt eine aktuelle Revision und verwendet den vorhandenen wiederholsicheren Zuordnungsbefehl. Eingaben bleiben nach Fehlern erhalten; erneutes Laden ist ohne Eingabeverlust möglich. Stornos verweisen zur Originalbuchung.
* Ein verspäteter Bankvorschlag konnte nach Wechsel der Bewegung stehen bleiben. Der Komponentenstatus ist jetzt an die Buchungsidentität gebunden. Namen und Vertragsnummern führen zu Konto und Vertrag; Beträge erscheinen im deutschen Format.
* Mahnausgang und zu prüfende Antworten zeigten nur 200 Einträge. Alle drei Mahnlisten laden nun weiter, behalten erfolgreiche Seiten bei Fehlern und verwerfen verspätete Antworten nach Filterwechsel. Ein fehlgeschlagener Abruf erscheint nicht als leerer Bestand.
* Mahnausgänge verlinken die betroffene Vertrags-Mahnakte. Versandvermerke erlauben kein zukünftiges Ist-Datum und sperren parallele Änderungen am Vertragskontext. Ein PostgreSQL-Test verwendet dafür zwei unterschiedliche Benutzer und unabhängige Verbindungen.
* Ein EUR-Bankoriginal konnte auf ein Konto eines anders denominierten Portfolios übernommen werden. Vorbereitung und Bestätigung verweigern diese unzulässige Gleichsetzung ohne erfundene Umrechnung.

## Kompatibilität und Prüfung

`GET /api/v1/bookings/allocations` bleibt standardmäßig die bestehende Liste. Mit `include_reservations=true` liefert es ausdrücklich `{allocations, reserved_amounts}`. Reservierungen enthalten ausschließlich Beträge bereits berechtigter Buchungen, keine Identitäten geschützter fremder Akten.

`GET /api/v1/deposits/{id}/payment-candidates` ergänzt `skip`, `limit` (Arbeitsschritt bis 250), `q`, `total`, `skip`, `limit`, `more`. Die bisherigen `items` und `more` bleiben erhalten; es gibt keine Gesamtgrenze von 200 Einträgen.

Regressionen prüfen Speicherfehler, gemischte und mehrfache Rückbuchungen, Portfoliobindung, Forderungsreservierungen, Wiederholungen nach Fehlern, 203 Kautionskandidaten, den 201. Mahneingang/-ausgang und verspätete Antworten bei Navigation. Die verpflichtende PostgreSQL-Matrix enthält jetzt zusätzlich die allgemeinen Zahlungs-, Kautions- und Mahnabläufe; übersprungene Prüfungen gelten dort nicht als bestanden.

Die abschließenden Nachweise des tatsächlich paketierten und installierten Stands liegen außerhalb des Repositorys unter `C:/Users/matth/Documents/ImmoManager-Sicherungen/20261021-Bank-Zahlungen-Mahnwesen-Kautionen/ABNAHME.json`. Sie werden erst nach erfolgreicher Gesamtprüfung erzeugt. Echte Bankzugänge und Nachrichtenversand sind nicht Teil der synthetischen Abnahme.
