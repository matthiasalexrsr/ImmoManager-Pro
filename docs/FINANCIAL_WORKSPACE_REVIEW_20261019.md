# Buchungen, Rechnungen, Abrechnungen und Mieterkonten

Diese Runde baut auf `f60f2002` auf und bewahrt die bestehenden Abrechnungsoriginale, Zahlungszuordnungen und Fachmodule. Es gibt keine Schemaänderung.

## Rechnungen und Zahlungsnachweise

`GET /api/v1/invoices/overview` ergänzt eine stabil nach ID sortierte, vollständig seitenweise abrufbare Rechnungsliste um `payment_summary`. Die bisherige Sammlung `/invoices` behält ihren Antwortvertrag. Die Übersicht verwendet dieselbe dezimalgenaue Abrechnung der Zahlungen wie die Rechnungsakte: einschließlich Stornos, Teilzahlungen, freigegebenen Teilbeträgen, Gutschriften, Skonto und ausdrücklich verknüpften Objektvertragszahlungen.

- `paid` bezeichnet tatsächlich zugeordnete wirksame Zahlungen.
- `open` bezeichnet den nachgewiesenen Restbetrag. `null` bedeutet ungeklärt und wird nicht als Nullbetrag ausgegeben.
- Ein alter manueller Status „bezahlt“ oder „teilbezahlt“ ohne Zahlungszuordnung bleibt im Datensatz erhalten. Die Übersicht zeigt den Zahlungsstand „Ungeklärt“ und weist den fehlenden Nachweis und den unbekannten Rest ausdrücklich aus.
- Noch nicht freigegebene Rechnungen werden gesondert ausgewiesen. Abgelehnte Rechnungen, Gutschriften und Überzahlungen behalten ihre eigene Bedeutung.
- Fälligkeit am heutigen Kalendertag bedeutet nicht „überfällig“. Die Fälligkeit einer geprüften Rechnung wird aus deren vereinbarten Zahlungsbedingungen abgeleitet, ohne die gespeicherte Rechnungsangabe beim Bearbeiten zu überschreiben.

Die Kennzahlen „Offen“ und „Überfällig“ verwenden Restbeträge; „Bezahlt“ verwendet Zahlungszuordnungen. Die verlinkten Quelllisten enthalten auch Teilzahlungen. „Zahlung zuordnen“ öffnet die Rechnungsakte und erzeugt keine bloße Statusänderung.

FIFO-Vorschläge berücksichtigen den verbleibenden Rechnungsbetrag und die gemeinsame verfügbare Zahlungskapazität. Bereits durch andere Rechnungen, Objektverträge, Mieten oder Kautionen verbrauchtes Geld wird nicht erneut vorgeschlagen. Bereits derselben Rechnung zugeordnete Buchungen werden nicht als zweite, unzulässige Zuordnung angeboten. Gleich datierte Buchungen haben in beiden Datenbankpfaden dieselbe Reihenfolge.

## Bedienung und Quellen

Die Zahlungsauswahl bietet Suche, weitere Ergebnisseiten und eine ausdrückliche Erweiterung auf andere Immobilien. Fehler bleiben sichtbar und wiederholbar; ein Fehler ersetzt keine Auswahl durch einen vermeintlichen Leerbestand. Veraltete Suchantworten werden verworfen. Ausgewählte Buchungen und erfasste Beträge bleiben beim erneuten Öffnen der Auswahl erhalten. Die gemeinsamen Dialoge werden außerhalb ihrer Formularcontainer angezeigt und laden ihre Stile auch beim direkten Einstieg in eine Rechnungsakte.

Das Mieterkonto speichert den Stichtag als `as_of` in der Adresse. Quellen zu Buchungen und Forderungen übernehmen ihn. Der Weg zu nicht zugeordneten Buchungen setzt auch den passenden Arbeitsfilter. Ein Wechsel der Partei übernimmt kein offenes Bearbeitungsformular der vorherigen Partei. Stammdatenänderungen aktualisieren die gemeinsamen Datenbestände.

Die ausgewählte Buchung verlinkt Immobilie, Einheit und Partei. „Mieterkonto zum Buchungsdatum“ öffnet genau diesen Stichtag.

Einzelabrechnungen und Forderungen/Guthaben sind über `statement_id` in beide Richtungen erreichbar. Der Filter wirkt vor der Seiteneinteilung auf dem Server und bleibt beim Wechsel zwischen offenen Forderungen und Guthaben erhalten. Die Rechnungsaufschlüsselung öffnet auch den zugehörigen Mietvertrag. Nicht verfügbare Einzelabrechnungen erhalten einen verständlichen Hinweis mit Rückweg.

Auch nach Zustellung dürfen die Forderungen einer finalisierten Abrechnung angelegt werden. Erneutes Ausführen erzeugt keine zweite Forderung. Entwürfe, offene Widerspruchsfassungen und ersetzte Fassungen werden darüber nicht neu abgerechnet. Ungültige Zustellwege werden vor einer Änderung zurückgewiesen.

## Prüfungen

Neue Regressionen liegen in `backend/tests/test_financial_workspaces.py`, `frontend/src/test/PaymentLookup.test.jsx` und den erweiterten Tests für Rechnungsprüfung, Abrechnungen, Mieterkonten und Forderungsverknüpfungen. Sie prüfen insbesondere belegte Teilzahlungen, Stornos, unbekannte Altbestände, identische Buchungsdaten, mehr als 25 Zahlungskandidaten, Wiederholung, veraltete Antworten und Parteienwechsel.

`scripts/application_browser_qa.mjs` prüft zusätzlich mit einer isolierten echten Anwendung:

1. Teilzahlung in der Rechnungsliste, Auswahl einer älteren Buchung hinter der ersten Seite, Speicherung und Vergleich mit der Rechnungsakte.
2. Buchung → Mieterkonto zum Buchungsdatum → zeitlich gefilterte Buchungsliste.
3. Finalisierte Abrechnung → Forderung/Guthaben → ursprüngliche Einzelabrechnung; wiederholte Forderungserzeugung ohne Dublette.
4. Die bisherigen Verwaltungsabläufe und sämtliche deklarierten Fachseiten bei 320, 360 und 1440 Pixeln.

Die Browserprüfungen verwenden eigene Testdaten und sperren die Ports der Hauptinstallation. Veröffentlichung und Umstellung der Hauptinstallation setzen die Prüfung des zusammengeführten Stands, Vollsicherung und Wiederherstellungsnachweis voraus. Die konkreten Ergebnisse gehören zum jeweiligen Freigabeprotokoll, nicht zu einem früheren Commit.
