# Dokumentseite und neue Fassungen

Stand 20. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Erstes Paket der Runde 11 aus der Vorschlagsliste der Runde 8.

## Die Seite eines Dokuments

Jedes Dokument hat eine eigene Seite unter `/documents/<id>`. In der Dokumentliste führt der Titel dorthin, außerdem die Zeilenaktion „Dokumentseite öffnen“. Auch „Dokument öffnen“ nach einem Brief oder einer Abrechnung führt jetzt auf diese Seite statt in die gefilterte Liste. Der Klick auf die übrige Zeile öffnet wie bisher die Schnellansicht der hochgeladenen Datei.

Die Seite zeigt:

* **Vorschau** der aktuellen Fassung (PDF und Bilder bis 20 MB, größere auf Knopfdruck). Ohne archivierte Fassung zeigt sie die hochgeladene PDF-Datei. Für Word, Excel und andere Formate gibt es keine Vorschau, nur den Download.
* **Angaben**: Typ, Datum, „Gültig bis“ mit Erinnerungsvorlauf, Schlagwörter, Beschreibung. „Angaben bearbeiten“ ändert genau diese Felder (PATCH). Die Zuordnung zu Immobilie, Einheit, Vertrag und Partei bleibt in der Dokumentliste, weil dort die Prüfung archivierter Originale greift.
* **Zuordnung** mit Links auf Immobilie, Einheit, Vertrag und die Parteienkarte.
* **Aufbewahrung**: Klasse, Frist, Grundlage, ob im Dokument festgelegt oder nach Typ, und ob das Löschen gesperrt ist.
* **Fassungen**: alle archivierten Fassungen, die neueste oben mit „aktuell“, je mit Zeitpunkt, Kommentar, Dateiname, Größe und Download. Ältere lädt „Ältere Fassungen laden“ nach.
* **Gelesener Text für die Suche**: Quelle (PDF-Text, Texterkennung, Office-Datei), Zeichenzahl, Zeitpunkt, aus welcher Fassung er gelesen wurde, und auf Wunsch die ersten 3000 Zeichen.
* Knöpfe für die Schnellansicht, die Dokumentwerkzeuge und „Brief und Frankatur“, unten „Dokument löschen“ mit der Aufbewahrungsprüfung aus Runde 10.

## Neue Fassung statt Doppelablage

Unter „Fassungen“ lädt **„Neue Fassung hochladen“** eine korrigierte oder neu eingescannte Datei als nächste Fassung desselben Dokuments hoch, mit optionalem Kommentar („Was hat sich geändert?“, bis 300 Zeichen). So entsteht kein zweites Dokument mit fast gleichem Titel.

* War noch nichts archiviert, wird zuerst die bisherige Datei unverändert als **Fassung 1** archiviert. Nichts geht verloren; jede Fassung bleibt herunterladbar.
* Die neue Fassung ist ab dann das, was Vorschau, Dokumentwerkzeuge und Volltextsuche verwenden. Die Schnellansicht der Liste zeigt weiterhin die ursprünglich hochgeladene Datei.
* Der Server prüft gegen den Stand, den die Seite geladen hat (Fassung, Prüfsumme, Revision). Hat jemand anderes inzwischen eine Fassung abgelegt, antwortet er mit 409, und die Seite muss neu geladen werden. Dieselbe Datei wie die aktuelle Fassung wird abgelehnt (422).
* Wiederholt die Seite nach einer verlorenen Antwort denselben Versand (gleiche Datei, gleicher Kommentar), schickt sie dieselbe Vorgangskennung und denselben Ausgangsstand; der Server antwortet mit dem bereits gespeicherten Ergebnis, statt eine dritte Fassung anzulegen.
* Fassungen gibt es nur für Dokumente, die einer Immobilie oder einem Vertrag zugeordnet sind (wie bei den Dokumentwerkzeugen). Bei anderen sagt die Seite das, statt einen Fehler zu zeigen.
* Dokumente mit archivierten Fassungen lassen sich wie alle archivierten Originale nicht löschen.

Schnittstelle: `GET /api/v1/documents/{id}/details` liefert Dokument, Namen der Zuordnung, Aufbewahrung, gelesenen Text und die ersten zehn Fassungen (`versions.unavailable` nennt den Grund, wenn es keine geben kann). `POST /api/v1/documents/{id}/work/versions` (multipart: `file`, `command_key`, `expected_sha256`, `expected_document_revision`, `expected_version`, `comment`) legt die neue Fassung ab und schreibt ein Ereignis „Neue Fassung“ in den Verlauf der Dokumentwerkzeuge.

## Volltextsuche liest bearbeitete Fassungen neu

Bisher las die Volltextsuche ein Dokument nur neu, wenn sich sein Datensatz änderte. Eine in den Dokumentwerkzeugen bearbeitete Fassung änderte den Datensatz nicht und blieb mit dem alten Text im Suchindex. Jetzt gilt ein Dokument auch dann als neu zu lesen, wenn seine neueste archivierte Fassung nicht die ist, aus der der Text stammt. Das betrifft neue Fassungen und Bearbeitungen gleichermaßen.

## Geprüft

* Backend (Speicher und SQL): neue Fassung mit Archivierung des Ausgangsoriginals, Wiederholung, veralteter Stand (409), identische Datei (422), Volltextindex liest die neue Fassung; Dokumentseite über HTTP, auch ohne Zuordnung und für ein unbekanntes Dokument (404).
* Oberfläche (vitest): Seite mit Vorschau der aktuellen Fassung, Zuordnung, Aufbewahrung, Fassungsliste, gelesener Text; Vorschau der hochgeladenen Datei ohne Fassung; Löschsperre; Hochladen gegen den aktuellen Stand; Wiederholung mit gleicher Vorgangskennung.
* Browser (Testversion, 1440 px und 390 px): Titel in der Liste öffnet die Seite, PDF-Vorschau, neue Fassung hochladen, Liste „Fassung 2 aktuell / Fassung 1 Eingangsoriginal“, Volltextsuche findet ein Wort, das nur in Fassung 2 steht, Angaben bearbeiten, kein horizontaler Überlauf, keine Konsolen- oder Serverfehler.
