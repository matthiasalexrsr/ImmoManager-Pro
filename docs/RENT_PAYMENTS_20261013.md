# Vertragszahlungen und Mietübersicht

Die Mietübersicht zeigt die vereinbarte Miete aus dem datierten Vertragsverlauf und den tatsächlich gebuchten Zahlungseingang. „Eingang buchen“ erstellt eine echte Buchung auf einem ausdrücklich gewählten Konto und eine manuelle Zuordnung zum Vertrag. Betrag, tatsächliches Eingangsdatum und Bemerkung werden gespeichert. Das Konto muss zum Portfolio des Vertrags gehören; die Schreibberechtigung für Buchungen und der aktuelle Portfoliozugriff werden serverseitig geprüft.

## Berechnungsgrundlage

Die Übersicht verwendet die vorhandene `LeaseEngine` einschließlich Teilmonaten und Mietänderungen. Zahlungen bis zum Stichtag decken zuerst ältere Mietmonate (FIFO). Stornos und Kautionsanteile werden nach den vorhandenen Zuordnungsregeln berücksichtigt. Das angezeigte Guthaben gilt für die angezeigten Verträge zum Stichtag, während Miete, gedeckter Betrag und offener Betrag den ausgewählten Mietmonat betreffen.

Manuell gepflegte Sollstellungen (`rent_charges`) und weitere Forderungen (`receivables`) bleiben eigenständige Vorgänge. Ihre Statusfelder sind kein Nachweis einer Kontobuchung; sie werden weder als Eingang übernommen noch zur Vertragsmiete addiert. Die Listen bleiben verlinkt. Mahnvorgänge können zusätzliche Forderungen berücksichtigen. Eine Vertragszahlung erklärt keine bestimmte zusätzliche Forderung oder manuelle Sollstellung für erledigt.

## Schnittstellen

- `GET /api/v1/rent-charges/ledger?month=JJJJ-MM&as_of=JJJJ-MM-TT&property_id=…`: Vertragszeilen und Summen; `as_of` und `property_id` sind optional. Jede Zeile liefert eine `contract_revision` für eine anschließende Zahlung.
- `POST /api/v1/rent-charges/contract-payment`: `contract_id`, `contract_revision`, `account_id`, positiver centgenauer `amount`, `booking_date`, optionaler `payment_text` und UUID `idempotency_key`. Die Antwort enthält die tatsächliche `booking`, `contract_id` und `replayed`.

Der POST erstellt Buchung, manuelle Vertragszuordnung und einen dauerhaften Befehlsbeleg in der vorhandenen Änderungshistorie innerhalb einer gemeinsamen Transaktion. Er verwendet die bestehenden Konten-, Eltern- und Speicherlocks. Eine veraltete Vertragsrevision lehnt einen neuen Befehl mit `RENT_PAYMENT_NOT_CREATED` ab. Zukünftige Eingangsdatumswerte und Vertragsentwürfe werden abgelehnt.

Eine Wiederholung desselben Befehls durch denselben angemeldeten Nutzer liefert dieselbe Buchung. Andere Angaben mit derselben Kennung werden abgelehnt. Wurde die Buchung zwischenzeitlich gelöscht, bearbeitet, anders zugeordnet, storniert oder zur Kaution verwendet, wird kein weiterer Eingang erzeugt und die ursprüngliche Buchung nicht unverändert bestätigt. Ein nicht mehr zugänglicher oder gelöschter Elternsatz liefert einen strukturierten Ausgang: entweder sicher nichts erstellt (`RENT_PAYMENT_NOT_CREATED`) oder bereits erfasst, inzwischen nicht verfügbar (`RENT_PAYMENT_RECORDED_UNAVAILABLE`). Dabei werden keine Angaben aus nicht zugänglichen Portfolios zurückgegeben.

## Wiederaufnahme und Grenzen

Vor dem Absenden speichert die deutsche Oberfläche den unveränderlichen Befehl nutzerbezogen im `sessionStorage` des Browser-Tabs. Nach Verbindungsabbruch, Navigation oder Neuladen kann „Buchung fortsetzen“ denselben Befehl prüfen. Solange der Ausgang unbekannt ist, sind die Zahlungsangaben gesperrt. Eine verspätete Antwort einer verlassenen Ansicht darf einen neueren gespeicherten Befehl nicht entfernen.

Diese Wiederaufnahme gilt für denselben Tab mit erhaltenem Sitzungsspeicher. Sie ist keine geräteübergreifende Warteschlange und überlebt das Löschen dieses Speichers nicht. Der serverseitige Befehlsbeleg bleibt dauerhaft erhalten; seine Wiederholungssicherheit setzt voraus, dass dieselbe Nutzerkennung und Befehls-UUID erneut gesendet werden. Nach Verlust der lokalen Kennung sollte zuerst die Buchungsliste geprüft werden, bevor ein neuer Eingang erfasst wird.

Ausgewählte Mieter werden im SQL-Speicher mit höchstens 500 Mieterkennungen pro Abfrage gelesen. Buchungs-, Zuordnungs- und Kautionslinks verwenden gefilterte Unterabfragen statt installationsweiter Buchungslisten oder großer Listen von Buchungskennungen. Bestehende Kautionslinks werden weiterhin einzeln auf Cent gerundet, auch bei älteren SQLite-Daten mit Bruchteilen eines Cents.
