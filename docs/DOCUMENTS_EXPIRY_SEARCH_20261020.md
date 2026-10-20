# Dokumente: Ablaufdaten mit Erinnerung und Volltextsuche

Stand 20. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Zweites und drittes Paket aus der Vorschlagsliste der Runde 8, nach „Briefkopf und Briefvorlagen“ (`LETTERS_20261020.md`).

## Ablaufdaten mit Erinnerung

**Daten.** Jedes Dokument kann ein Ablaufdatum (`valid_until`) und einen Vorlauf in Tagen (`reminder_days`, 0 bis 730, leer = 30) haben. Migration **`d8a1c3e5f7b9`** hinter `c6e8a0b2d4f3`: zwei Spalten und ein Index auf `valid_until`. Sie ist wie die Vorgänger abgesichert, sodass mit `create_all` angelegte Datenbanken die Migration bestehen. Ein Downgrade wird verweigert, solange ein Dokument ein Ablaufdatum oder einen Vorlauf hat. Der JSON-Export hat Formatversion 12, damit ältere Programmversionen ihn ablehnen, statt die Ablaufdaten stillschweigend zu verlieren.

**Erinnerung.** Der tägliche Job `documents.expiry` läuft um 06:40 Uhr (Europe/Berlin), nach den Fristen der Objektverträge. Sobald das Erinnerungsfenster eines Dokuments beginnt (Ablaufdatum minus Vorlauf), entstehen eine Aufgabe (fällig am Ablaufdatum, am Objekt und an der Einheit des Dokuments) und eine Benachrichtigung („Läuft ab: …“ bzw. „Abgelaufen: …“). Das geschieht genau einmal je Dokument und Ablaufdatum, abgesichert über das Protokoll erledigter Erinnerungen (`document:<id>:expiry`, Regelversion v1). Ein neues Datum, etwa nach der Erneuerung oder einer Korrektur, erinnert erneut; dasselbe Datum nie zweimal, auch nicht bei mehreren Prozessen. Höchstens sieben Tage vor dem Ablauf sind Aufgabe und Hinweis dringend.

**Oberfläche.** Im Dokumentformular stehen „Gültig bis“ und „Erinnern (Tage vorher)“ mit Beispielen: Energieausweis 10 Jahre, Rauchmelder- oder Wartungsnachweis 1 Jahr, Police bis zum Ablauf. Die Dokumentliste hat die Spalte „Gültig bis“ mit „läuft ab“ oder „abgelaufen“, den Filter „Läuft ab oder abgelaufen“ und eine Kennzahl dazu. Archivierte Originale (Briefe, Protokolle) können ein Ablaufdatum bekommen, denn die Archivprüfung vergleicht nur die Zuordnung.

## Volltextsuche im Dokumentinhalt

**Texterkennung.** Der Job `documents.text_index` liest den Text jedes Dokuments aus seiner Datei: beim archivierten Original (Briefe, Protokolle, Abrechnungen) aus der aktuellen Fassung, sonst aus der hochgeladenen Datei. PDF liefern ihre Textebene über **pypdf 6.19.0** (neue Abhängigkeit, in `requirements.txt`, `constraints.txt` und im Windows-Paket). Gescannte PDF ohne Textebene und Bilder werden nur erkannt, wenn PyMuPDF und Tesseract installiert sind (höchstens 20 Seiten); ohne sie bleibt das Dokument „ohne lesbaren Text“. Textdateien (txt, csv, md) und Office-Dateien (docx, odt, xlsx, ods) liefern ihren Text direkt. Grenzen: 50 MB je Datei, 500 PDF-Seiten, 500 000 Zeichen. Alles geschieht auf dem Rechner; nichts wird an einen Dienst geschickt.

**Ablauf.** Ein neues, geändertes oder importiertes Dokument stößt die Indizierung im Hintergrund an (dauerhafter Job, kein Warten in der Anfrage); täglich um 05:30 Uhr holt ein Lauf Versäumtes nach. Jeder Abschnitt von 50 Dokumenten wird mit seinem Prüfpunkt festgeschrieben, ein unterbrochener Lauf setzt dort fort. Ein Dokument wird nur neu gelesen, wenn es noch keinen Text hat oder seit dem Lesen geändert wurde; eine Datei ohne lesbaren Text bekommt eine leere Zeile (Quelle `none`), damit sie bis zur nächsten Änderung nicht erneut gelesen wird. Beim Löschen eines Dokuments verschwindet sein Text mit.

**Daten.** Migration **`e2b4d6f8a0c1`** hinter `d8a1c3e5f7b9`: Tabelle `document_texts` (eine Zeile je Dokument, Fremdschlüssel mit `ON DELETE CASCADE`). Der Text ist abgeleitet und jederzeit neu erzeugbar; deshalb entfernt ein Downgrade die Tabelle einfach, gehört nicht zum JSON-Export und ändert dessen Formatversion nicht. Die Tabelle zählt zu den internen Tabellen der Portfolio-Grenze: Suchergebnisse entstehen immer über die Dokumente, die das Konto sehen darf.

**Suche.** `GET /api/v1/documents/search?q=…` sucht den Begriff wörtlich und ohne Groß-/Kleinschreibung (wie die globale Suche, ohne Platzhalterzeichen) und liefert die Treffer, neueste zuerst, mit einem Ausschnitt um die Fundstelle. `GET /api/v1/documents/text-index` nennt, wie viele sichtbare Dokumente durchsuchbar sind und wie viele keinen lesbaren Text haben; `POST /api/v1/documents/text-index` stößt die Indizierung sofort an. Auch die globale Suche findet Dokumente jetzt über ihren Inhalt.

**Oberfläche.** Die Dokumentseite hat über der Liste den Bereich „Volltextsuche in Dokumenten“: Suchfeld, Treffer mit Ausschnitt und Zuordnung (Objekt, Einheit, Vertrag), Stand („12 von 14 Dokumenten im Inhalt durchsuchbar“) und, solange Dokumente noch gelesen werden, „Jetzt lesen“. Ein Treffer öffnet das Dokument.

## Stand der Umsetzung

- [x] Ablaufdaten: Modell, Migration, Job, Oberfläche, Tests (`test_document_expiry.py` auf SQL und Speicher, Migrationstest, Scheduler)
- [x] Volltextsuche: Texterkennung, Tabelle und Migration, Job, Suche, globale Suche, Portfolio-Grenze, Oberfläche, Tests (`test_document_text.py` auf SQL und Speicher, archivierter Brief durchsuchbar, Portfolio-Grenze über HTTP, Migrationstest, Scheduler, `DocumentContentSearch.test.jsx`)
