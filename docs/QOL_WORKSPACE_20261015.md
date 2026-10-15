# Persönlicher Arbeitsstand und tägliche Verwaltung

Umsetzung der am 15. Oktober beauftragten QoL-Funktionen auf dem zuletzt
überprüften Claude-Stand. FastAPI/React und die vorhandenen Fachabläufe bleiben
die gemeinsame Grundlage. Keine echten Nachrichten oder externen Übertragungen
werden durch Entwurfssicherung, Dublettenprüfung oder Gesprächsnotizen ausgelöst.

## Bedienung

| Funktion | Einstieg und Verhalten |
| --- | --- |
| Entwürfe | Unterstützte Formulare sichern bearbeitbare Eingaben automatisch. Beim Wiederöffnen ausdrücklich wiederaufnehmen oder verwerfen. Änderungen an Quelle oder zugehöriger Akte müssen verglichen werden. Ein gelöschter Ursprung bleibt als kopierbarer Entwurfsinhalt sichtbar. |
| Mehrere Ansichten | Über einer Tabelle einen Namen eingeben und „Ansicht speichern“. Filter, Suche, Spalten, Reihenfolge und Sortierung gehören zur Ansicht; fachliche Zusatzfilter werden mitgespeichert. |
| Gemerkte Akten | „Merken“ an Immobilien, Einheiten und Parteien. Arbeitszentrale und Aktenbereiche zeigen Favoriten und zuletzt geöffnete Vorgänge. |
| Arbeitszentrale | Aufgaben, Instandhaltung, Rechnungen, Forderungen, Belege, Mahnvorgänge, fehlende Vertragsunterlagen, Vertragsfristen, Zählerprüfungen, fehlende Ablesungen und offene Mieterwechsel. Quelle und Umfang bleiben sichtbar; weitere Seiten sind erreichbar. |
| Zurückstellen | Einen konkreten Hinweis mit Begründung bis zu einem Datum zurückstellen. Die Zurückstellung ist persönlich und ändert den Fachvorgang nicht. Neue Mahnakten übernehmen keine Zurückstellung eines geschlossenen Falls. |
| Aktenchronik | Aktivitäten in Immobilien-, Einheiten- und Parteienakten zusammenhängend ansehen, einschließlich zugehöriger Originale, Zahlungen, Aufgaben, Schäden und künftig erfasster Feldänderungen. |
| Gespräch und Wiedervorlage | In einer Akte „Gespräch / Wiedervorlage“ öffnen. Notiz und optionale Folgeaufgabe werden gemeinsam gespeichert; eine Wiederholung legt keine zweite Aufgabe an. |
| Schnelländerung | In Aufgabenlisten Status, Zuständigkeit und Fälligkeit direkt ändern. Eine zwischenzeitliche Änderung führt zu einem verständlichen Konflikt. |
| Rückgängig | Aufgabenänderung oder bestätigte Belegzuordnung zurücknehmen, solange kein späterer Bearbeitungsstand überschrieben würde. Finanzbuchungen verwenden den bestehenden verknüpften Stornoablauf. |
| Dokumentenfolge | Dokumenteneingang analysieren, Original ansehen, Vorschläge prüfen, speichern und zum nächsten Beleg wechseln. Nur eine ausdrücklich gewählte Zuordnung wird als Vorschlag übernommen; individuelle Titel und Beträge werden nicht kopiert. |
| Dubletten | Kontakte, Rechnungen und Dateien vergleichen. Berechtigte Ausnahmen benötigen eine Begründung. Treffer sind Hinweise; es wird nichts automatisch zusammengeführt oder gelöscht. |
| Kennzahlen | Quellvorgänge über die jeweilige Kennzahl öffnen. Zeitraum und fachliche Auswahl bleiben erhalten; Rückzahlungen und Stornos reduzieren ihre ursprüngliche Seite. |
| Zurücknavigation | Suche, Tabellenfilter, Seitenposition, Scrollposition und Markierung der zuletzt bearbeiteten Zeile bleiben je Benutzer und konkreter Auswahl erhalten. Neue Quellenlinks übernehmen ihre eigene Auswahl. |

## Persistenz, Konflikte und Berechtigungen

- Persönliche Arbeitsstände liegen in sieben `workspace_*`-Tabellen und sind
  ausschließlich ihrem angemeldeten Eigentümer zugeordnet. Benutzerkennungen
  im Anfragekörper gewähren keinen Zugriff auf fremde Arbeitsstände.
- Lesen, Wiederaufnehmen und Wiederholen prüfen die aktuellen Objekt- und
  Benutzerrechte. Favoriten und Verlauf gewähren keine zusätzlichen Rechte.
- Entwürfe speichern keine Passwörter, Zugriffsschlüssel oder Dateiobjekte.
  Noch nicht bestätigte Eingaben besitzen zusätzlich einen benutzergebundenen
  Browserpuffer. Dessen Wiederaufnahme verlangt eine erfolgreiche Serverprüfung.
- Unklare Sicherungsantworten behalten denselben Wiederholungsschlüssel. Auch
  das Verwerfen und die Bereinigung nach erfolgreichem Fachspeichern sind nach
  einem unmittelbaren Seitenwechsel wiederholbar.
- Ein Entwurf ist keine Freigabe, Zahlung oder Veröffentlichung. Nach der
  Wiederaufnahme müssen sicherheitsrelevante Bestätigungen erneut erfolgen.
- Revisionen und Quellabhängigkeiten verhindern das Überschreiben paralleler
  Änderungen. Eine erneut veränderte Vergleichsgrundlage verlangt einen neuen
  Vergleich; eine Wiederholung derselben bestätigten Aktion erzeugt keine Dublette.
- Gesprächsnotizen, Bearbeitungsnachweise, Dokumenteneingang und begründete
  Dubletten-Ausnahmen sind gemeinsame Fachdaten und gehören zum Snapshotformat 8.
  Private Arbeitsstände werden nicht in fachliche JSON-Datenaustausche exportiert.
  Vollständige Datenbanksicherungen enthalten ihre Tabellen.

Die Migrationen `a71c4e9f2036` und `b82d5fa03147` ergänzen diese Datenstrukturen.
Der unterstützte explizite Upgradepfad übernimmt auch bereits angelegte Tabellen,
ohne vorhandene Inhalte zu verwerfen. Normale Produktionsstarts bleiben vom
Schema-Upgrade getrennt.

## Schnittstellen

- `/workspace/drafts`, `/views`, `/view-state`, `/recents`, `/favorites`,
  `/deferrals`: persönliche Daten, Revision und Wiederholungsschlüssel.
- `/workspace/source/{kind}/{id}`: berechtigte Vergleichsgrundlage einschließlich
  Revision und Abhängigkeitsständen; Entwurfsübernahme über `/drafts/{id}/rebase`.
- `/work-center/items`, `/summary`, `/timeline`: gefilterte Quellen, genaue
  Zählwerte und fortsetzbare Navigation.
- `/work-center/notes`, `/quick-edits`, `/quick-edits/{id}/undo`: atomare
  Fachbefehle mit Ergebnisnachweis und Konfliktprüfung.
- `/work-center/documents`: dauerhafte Analysezustände, Prüfung und Fortsetzung.
  Ein abgelaufener Verarbeitungsversuch kann ein Ergebnis seines Nachfolgers
  nicht überschreiben.
- `/work-center/duplicates/check`, `/duplicates/exceptions`: nebenwirkungsfreie
  Prüfung beziehungsweise ausdrücklich begründete Ausnahme. Auch Leser dürfen
  prüfen; eine Ausnahme benötigt Schreibrechte.

Seitenbudgets begrenzen einzelne Antworten; sie beschneiden keinen Gesamtbestand.
Für Dateidubletten wird der tatsächlich indizierte Umfang angezeigt. Historische
noch nicht indizierte Dokumente lassen sich über alle Seiten des Eingangs
verarbeiten. Prüfsummen bleiben auch bei fehlgeschlagener Texterkennung erhalten.
Archivierte Originale besitzen bereits verifizierbare Prüfsummen.

## Prüfung und praktische Grenzen

Automatisierte Regressionen liegen insbesondere in `test_workspace.py`,
`test_business_qol.py`, `test_business_qol_review.py`,
`test_business_contact_matching.py`, `test_workspace_scale.py` sowie den
Frontend-Prüfungen `WorkspaceForms`, `WorkspaceAnchorDraft`,
`WorkspaceNavigation`, `WorkspaceSources`, `WorkCenter`, `DocumentIntakeQueue`
und `ContractWizardBridge`.

Der PostgreSQL-Releaseprüfer nimmt zusätzlich `test_workspace_postgres.py` auf.
Er erzeugt eine eigene Datenbank, prüft unabhängige Schreibverbindungen und
verweigert einen erfolgreichen Abschluss mit übersprungenen Teilprüfungen.

Die echten Browserabläufe sind über `scripts/run_workspace_browser_qa.py`
reproduzierbar. Voraussetzung ist ein gebautes Frontend sowie `--playwright`
mit einem ESM-Modul, das `chromium`, `request` und `expect` exportiert. Der
Prüfer startet ausschließlich eine eigene lokale Installation mit synthetischen
Daten und beendet seine Prozesse anschließend selbst.

Feldhistorie beginnt mit dieser Umsetzung; fehlende historische Änderungen
werden nicht erfunden. Direkte administrative SQL-Bulkoperationen besitzen keine
automatisch erzeugte fachliche Feldhistorie. Vertragsfristberechnungen und seltene
Normalisierungsfälle können vollständige, speicherbegrenzt gelesene Kandidaten
benötigen; dafür wird keine feste Abschneidegrenze eingeführt. Diese Änderungen
beweisen weder eine allgemeine zwanzigjährige Kapazitätsgarantie noch die externe
WISO-/TEHA-Schreibabnahme.
