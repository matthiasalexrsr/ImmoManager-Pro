# Vorschläge und offene Entscheidungen umgesetzt (Runde 15, 22.10.2026)

Umgesetzt wurden die Vorschläge aus der Prüfung von Logik und Wartbarkeit ([LOGIC_MAINTENANCE_AUDIT_20261022.md](LOGIC_MAINTENANCE_AUDIT_20261022.md)) und die offenen Entscheidungen der Rechenprüfung ([CALCULATION_AUDIT_20261021.md](CALCULATION_AUDIT_20261021.md)). Neu hinzugekommen ist die Erfassung von Entnahmen, Ausschüttungen und Einlagen. Jede Änderung hat einen Test; Speicher- und SQL-Store, die Migrationen und das PostgreSQL-Gate sind geprüft.

## Vorschläge aus Runde 14

| Vorschlag | Umsetzung |
|---|---|
| Budget-Ist auf Anfrage aus den Buchungen (einstellbar) | Ein Budget kann Buchungskategorien nennen (Migration `e4b6d8f0a2c3`). „Ist aus Buchungen“ zeigt, was die Buchungen der Immobilie im Budgetjahr in diesen Kategorien ausgegeben haben, mit den Buchungen dahinter. Gespeichert wird erst beim Übernehmen, und nur, wenn sich die Buchungen inzwischen nicht geändert haben. Erstattungen und Stornos mindern das Ist. Miete, Einnahmen- und Privatkategorien zählen nie. Ohne Kategorien bleibt das Ist von Hand gepflegt. |
| Doppelte IBANs anzeigen | Die Prüfliste nennt Konten mit derselben IBAN (Eintrag „IBAN doppelt“, die IBAN ist maskiert). |
| Ein „Heute“ | `backend/domain/clock.py` liefert `local_today()` und `local_date()`: das Kalenderdatum der Installation in Europe/Berlin. 31 Module nahmen `date.today()`, die Lastschriftdatei und die Aufbewahrung sogar das UTC-Datum. Im Docker-Container (UTC) galt zwischen 0 und 2 Uhr noch der Vortag. `test_clock.py` schlägt bei jedem neuen `date.today()`, `datetime.now().date()` oder `<…>_at.date()` fehl. Das Docker-Image behält bewusst UTC, damit sich die Zeitstempel bestehender Installationen nicht verschieben. |
| `iban_encryption.py` entfernen | Entfernt, samt Tests und Eintrag im Windows-Paket. |
| Update-Quelle prüfen | Zeigt `origin` des Checkouts auf ein anderes Repository als `UPDATE_REPO_URL`, bietet die Update-Prüfung keine Installation an und erklärt warum. Das Einspielen lehnt der Updater ab, bevor er etwas sichert oder ändert. Zugangsdaten im Remote werden nie angezeigt. |
| pip festlegen | `requirements-pip.txt` legt den Installer fest (pip 26.2.1). CI, Release-Builds und Docker-Image installieren ihn zuerst. Ein Test verlangt das für jede Pipeline. |

## Neu: Entnahmen, Ausschüttungen und Einlagen

Eine Kategorie vom Typ **„Privat (Entnahme/Einlage)“** hält das eigene Geld der Eigentümer. Eine solche Buchung verändert den Kontostand, ist aber weder Einnahme noch Ausgabe. Negativ ist sie eine Entnahme oder Ausschüttung, positiv eine Einlage aus Privatmitteln; ein Storno mindert die Buchung, die er aufhebt.

- Zahlungsübersicht, Finanzbericht „Zahlungen“, Buchungsseite und Dashboard zeigen Entnahmen und Einlagen neben Einnahmen und Ausgaben.
- Periodenergebnis, Ergebnisbericht, Prognose-Durchschnitte und Budget-Ist lassen sie aus.
- **Steuer:** Die Jahresauswertung ordnet nur nach den Regeln der Steuervorbereitung zu. Für eine Privatkategorie bitte die Regel „nicht berücksichtigt – privat“ anlegen, dann ist die Auswertung vollständig.

## Offene Entscheidungen aus Runde 12

| ID | Entscheidung und Umsetzung |
|---|---|
| R12-03 | Die Prüfliste nennt Verträge, deren Mietverlauf nach dem Vertragsbeginn beginnt (bei Übernahme: nach „Mietkonto ab“). |
| R12-07 | **Heizkosten nach HeizkostenV:** Eine Kostenposition kann einen Verbrauchsanteil von 50 bis 70 % haben (§ 7) und einen Schlüssel für die Grundkosten (Standard: Fläche des Objekts; Migration `b8f0a2c4d6e7`). Die Abrechnung teilt sie in „– Verbrauch 70 %“ und „– Grundkosten 30 %“. Ein Verbrauchsanteil ohne Verbrauchsschlüssel oder ohne Grundkostenschlüssel sperrt die Abrechnung. Heizkosten, die nicht nach Verbrauch verteilt werden, bekommen eine Warnung mit § 12 (Kürzungsrecht 15 %). |
| R12-09 | Beobachten (höchstens 1 ct bei Ein- und Auszug im selben Jahr). Keine Änderung. |
| R12-12 | Das Anschreiben zur Abrechnung warnt, wenn bis zum Ende des Abrechnungszeitraums Miete offen ist. Offene Vorauszahlungen sind mit der Abrechnung nicht mehr gesondert einforderbar (BGH VIII ZR 271/10). |
| R12-14 | **Zehn-Tage-Regel:** Eine Buchung kann ihr Steuerjahr nennen (Migration `a6d8f0b2c4e5`). Das geht nur vom 22.12. bis 10.01. und nur für das Nachbarjahr (§ 11 Abs. 1 Satz 2 EStG). Die Jahresauswertung wählt danach aus; eine Januarzahlung für das Vorjahr zählt, sobald sie bis zum Stichtag gezahlt ist. Die Prüfliste fragt bei Mieterzahlungen der letzten Dezembertage nach dem Steuerjahr. Quellen ohne Steuerjahr bleiben unverändert, frühere Auswertungen behalten also ihren Prüfwert. |
| R12-15 | **Sonstige Forderung:** Eine Forderung kann als eigene Forderung markiert werden, etwa für Schaden oder Schlüssel (Migration `f5c7e9a1b3d4`). Periodenergebnis und Ergebnisbericht zählen sie zum Fälligkeitstag als Ertrag. Unmarkierte Forderungen zählen weiter nicht, denn sie können eine Monatsmiete doppeln. |
| R12-16 | **Art der Mietänderung:** Mietanpassungen gibt es auch als Vergleichsmiete, Modernisierung und Vereinbarung. Ein Mietstand aus einer Modernisierung startet keine Sperr- und Wartefrist nach § 558. Seine Erhöhung kommt im Mieterhöhungsschreiben und in der Prüfliste zur Kappungsgrenze hinzu (§ 558 Abs. 1 Satz 3, Abs. 3). Schreiben ohne solche Stände behalten ihre Quelle. |
| R12-17 | Die Prüfliste nennt laufende Verträge ohne Mietverlauf. |
| R12-18 | **Mahngebühren:** Standard sind jetzt 2,50 € je Mahnung, statt 2,50 / 5,00 / 5,00 € (bei der Kampagne 2,50 / 5,00 / 7,50 €). Gespeicherte Stufeneinstellungen bleiben, wie sie sind. |
| R12-19 | **Fälligkeit ab Zustellung:** Eine Nachzahlung ist 30 Tage nach dem Zustellvermerk der Abrechnung fällig, gerechnet vom Tag in Berlin. Ohne Vermerk wartet sie, bis die Zustellung bestätigt ist; die Abrechnungsseite fragt nach. Guthaben werden wie bisher angelegt. |
| R12-20 | **Mieterkonto mit allen Forderungen:** Je Vertrag und gesamt zeigt das Mieterkonto die fälligen Forderungen und Guthaben und den Gesamtsaldo. Ist Miete überzahlt, während eine Forderung offen ist, schlägt es den Ausgleich aus der letzten Zahlung vor, die früheste Fälligkeit zuerst (§ 366 Abs. 2 BGB). „Ausgleich buchen“ bucht ihn über den bestehenden Forderungsausgleich; von selbst wird nichts gebucht. |

## Bei dieser Runde gefunden

- **Mitternacht in Berlin:** Die Suite lief zusätzlich mit der Uhr auf 0:35 Uhr in Berlin (22:35 UTC). Dabei kam ein Fehler heraus: Ein um diese Zeit abgelehnter Interessent zählte schon einen Tag seit der Entscheidung. Dieselbe Ursache, nämlich ein UTC-Zeitstempel ohne Umrechnung zum Tag gemacht, betraf auch den Zustelltag einer Abrechnung (Abrechnungsfrist, Briefe), den Anlagetag von Dokumenten (Aufbewahrung) und von Daueraufgaben. Behoben mit `local_date()`; der Wächtertest erkennt diese Schreibweise jetzt.

## Beim Update

- **Fünf neue Spalten** in vier Migrationen. Sie sind alle optional und werden nur angelegt, wo sie fehlen. Ein Downgrade wird abgelehnt, solange eine Spalte benutzt wird.
- **Zahlungsübersicht:** Bisher ohne Kategorie gebuchte Entnahmen zählen weiter als Ausgabe. Sie fallen erst aus Ergebnis und Ausgaben, wenn sie eine Privatkategorie bekommen.
- **Mahngebühren:** Installationen ohne gespeicherte Stufeneinstellungen erheben für neue Mahnschreiben 2,50 €. Abgeschlossene Schreiben bleiben, wie sie sind.
- **Forderungen erzeugen** legt Nachzahlungen nicht zugestellter Abrechnungen erst nach Bestätigung an.
