# Dokumente: Ablaufdaten mit Erinnerung und Volltextsuche

Stand 20. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Zweites und drittes Paket aus der Vorschlagsliste der Runde 8, nach „Briefkopf und Briefvorlagen“ (`LETTERS_20261020.md`).

## Ablaufdaten mit Erinnerung

**Daten.** Jedes Dokument kann ein Ablaufdatum (`valid_until`) und einen Vorlauf in Tagen (`reminder_days`, 0 bis 730, leer = 30) haben. Migration **`d8a1c3e5f7b9`** hinter `c6e8a0b2d4f3`: zwei Spalten und ein Index auf `valid_until`. Sie ist wie die Vorgänger abgesichert, sodass mit `create_all` angelegte Datenbanken die Migration bestehen. Ein Downgrade wird verweigert, solange ein Dokument ein Ablaufdatum oder einen Vorlauf hat. Der JSON-Export hat Formatversion 12, damit ältere Programmversionen ihn ablehnen, statt die Ablaufdaten stillschweigend zu verlieren.

**Erinnerung.** Der tägliche Job `documents.expiry` läuft um 06:40 Uhr (Europe/Berlin), nach den Fristen der Objektverträge. Sobald das Erinnerungsfenster eines Dokuments beginnt (Ablaufdatum minus Vorlauf), entstehen eine Aufgabe (fällig am Ablaufdatum, am Objekt und an der Einheit des Dokuments) und eine Benachrichtigung („Läuft ab: …“ bzw. „Abgelaufen: …“). Das geschieht genau einmal je Dokument und Ablaufdatum, abgesichert über das Protokoll erledigter Erinnerungen (`document:<id>:expiry`, Regelversion v1). Ein neues Datum, etwa nach der Erneuerung oder einer Korrektur, erinnert erneut; dasselbe Datum nie zweimal, auch nicht bei mehreren Prozessen. Höchstens sieben Tage vor dem Ablauf sind Aufgabe und Hinweis dringend.

**Oberfläche.** Im Dokumentformular stehen „Gültig bis“ und „Erinnern (Tage vorher)“ mit Beispielen: Energieausweis 10 Jahre, Rauchmelder- oder Wartungsnachweis 1 Jahr, Police bis zum Ablauf. Die Dokumentliste hat die Spalte „Gültig bis“ mit „läuft ab“ oder „abgelaufen“, den Filter „Läuft ab oder abgelaufen“ und eine Kennzahl dazu. Archivierte Originale (Briefe, Protokolle) können ein Ablaufdatum bekommen, denn die Archivprüfung vergleicht nur die Zuordnung.

## Stand der Umsetzung

- [x] Ablaufdaten: Modell, Migration, Job, Oberfläche, Tests (`test_document_expiry.py` auf SQL und Speicher, Migrationstest, Scheduler)
- [ ] Volltextsuche
