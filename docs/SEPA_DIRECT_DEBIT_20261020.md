# SEPA-Lastschriftdatei für Mieten

Stand 20. Oktober 2026, Branch `claude/dreamy-gauss-nmaxhn`. Zweites Paket der Runde 11.

Das Programm **erstellt** die Lastschriftdatei; es sendet nichts. Die Datei wird im Online-Banking als SEPA-Sammellastschrift hochgeladen, dort prüft die Bank Summe und Anzahl noch einmal.

## Voraussetzungen

* **Konto mit IBAN** unter Konten (Finanzen → Konten). Eingezogen wird auf dieses Konto, und nur für Verträge im Bestand (Portfolio) dieses Kontos. So landet die Miete eines Eigentümers nicht auf dem Konto eines anderen.
* **Gläubiger-Identifikationsnummer** von der Deutschen Bundesbank (Antrag über glaeubiger-id.bundesbank.de). Sie wird beim ersten Mal im Dialog eingegeben, mit Prüfziffer geprüft und je Konto gemerkt (Einstellungsregel `sepa_creditor:<Konto>`, mit Änderungsprotokoll).
* **Beim Mieter** (Mieter bearbeiten): Zahlungsart „SEPA-Lastschrift“, Mandatsreferenz (bis 35 Zeichen, ohne Leerzeichen und Umlaute), Datum der Mandatsunterschrift, IBAN des Mieters (Prüfziffer wird geprüft), optional BIC und Kontoinhaber, wenn das Konto nicht dem Mieter gehört.
* **Vorabankündigung**: Der Mieter muss Betrag und Termin vorher kennen (in der Regel 14 Tage, kürzer, wenn vereinbart). Bei gleichbleibender Miete genügt meist die Angabe im Mietvertrag oder Mandat. Das Programm prüft das nicht.

## Ablauf

Forderungen → **„SEPA-Lastschriftdatei …“** (für Eigentümer, Verwaltung und Buchhaltung):

1. Konto, Monat (vorgeschlagen: der nächste) und Fälligkeit wählen. Vorgeschlagen wird der erste Bankarbeitstag des Monats, frühestens der nächste Bankarbeitstag nach heute. Wochenenden und TARGET2-Feiertage (Neujahr, Karfreitag, Ostermontag, 1. Mai, 25./26. Dezember) werden abgelehnt, mit dem nächsten möglichen Tag.
2. Die Tabelle zeigt jeden Vertrag des Bestands, dessen Mieter per Lastschrift zahlt, mit dem Betrag: die **Monatsmiete aus dem Mietkonto**, soweit Zahlungen sie nicht schon decken (dieselbe Verrechnung wie im Mietkonto: ältere Rückstände zuerst, ein Guthaben mindert die Miete), dazu **gespeicherte offene Forderungen** mit Fälligkeit im Monat (etwa eine Nachzahlung aus der Nebenkostenabrechnung). Rückstände aus Vormonaten und Rücklastschriften zieht die Datei nicht ein; die gehören ins Mahnwesen.
3. Was fehlt, steht in der Zeile („IBAN fehlt.“, „Datum der Mandatsunterschrift fehlt.“, „Die Prüfziffer der IBAN stimmt nicht.“). Solche Verträge lassen sich nicht auswählen.
4. „Datei erstellen“ speichert `SEPA-Lastschriften_<Monat>_<Fälligkeit>.xml`.

## Schutz vor doppeltem Einzug

Jede Datei wird mit ihren Sollstellungen im Änderungsprotokoll vermerkt (`sepa_debit_file`). Öffnet man den Dialog erneut, sind bereits geschriebene Verträge nicht vorausgewählt und als „Schon in einer Datei vom …“ markiert. Wer sie trotzdem aufnimmt (etwa weil die Bank die Datei abgelehnt hat), bestätigt das ausdrücklich; der Server lehnt sonst mit 409 ab. Geht die Antwort beim Erstellen verloren und der Knopf wird erneut gedrückt, liefert der Server dieselbe Datei mit derselben Kennung zurück, statt eine zweite anzulegen.

## Die Datei

ISO 20022 **pain.008.001.08**, wie es die deutschen Banken seit November 2023 erwarten (DFÜ-Abkommen Anlage 3, Version 3.7): ein Auftrag je Datei, SEPA-Basislastschrift (CORE), Sequenz RCUR (seit 2016 auch für die erste Lastschrift zulässig), Zweck RENT, Entgelt SLEV. Namen und Verwendungszweck werden in den SEPA-Zeichensatz übertragen (ä → ae, ß → ss, & → +). Ohne BIC steht „NOTPROVIDED“ (IBAN-only). Die Ende-zu-Ende-Referenz ist Monat und Vertragsnummer (`202611-MV-2020-010`), damit eine Rücklastschrift im Kontoauszug zuzuordnen ist. Die Tests prüfen die erzeugten Dateien gegen das offizielle Schema.

Nicht enthalten: Firmenlastschrift (B2B), mehrere Fälligkeiten in einer Datei, automatische Vorabankündigung, Versand per EBICS oder FinTS.

## Datenmodell

Migration `a5c7e9b1d3f5` ergänzt bei Mietern `sepa_iban`, `sepa_bic`, `sepa_account_holder`, `sepa_mandate_date` (geschützt, additiv; ein Downgrade wird abgelehnt, solange Werte gespeichert sind). Der JSON-Export hat das Format 14. Die DSGVO-Anonymisierung leert die neuen Felder mit. Die Testversion gibt ihren Lastschrift-Mietern eine IBAN und ein Mandatsdatum.

Schnittstelle: `GET /api/v1/receivables/sepa-debits/preview?account_id=…&month=JJJJ-MM[&collection_date=…]`, `POST /api/v1/receivables/sepa-debits/files` (`account_id`, `month`, `collection_date`, `creditor_id`, `creditor_name`, `contract_ids`, `allow_repeat`, `idempotency_key`; Antwort mit `xml`, `filename`, `message_id`).

## Geprüft

* Regeln: IBAN (Länge je Land, Prüfziffer), BIC, Gläubiger-ID mit Prüfziffer, Mandatsreferenz, Zeichensatz, Ostern/TARGET2-Tage, Fälligkeit.
* Speicher und SQL: Vorschau nur für Lastschriftzahler des Bestands; Miete aus dem Mietkonto plus Nachzahlung und Stellplatz des Monats, nicht der Vormonat; fehlende IBAN; nichts offen; Datei gegen das XSD gültig; Wiederholung liefert dieselbe Datei und keinen zweiten Vermerk; zweite Datei nur mit Bestätigung; abgelehnt: fremder Bestand, unvollständiger Vertrag, falsche Gläubiger-ID, Samstag, heute, leere Auswahl, Technik-Rolle (403). Mieter-IBAN wird geprüft und normalisiert, Anonymisierung leert sie. Migration mit Downgrade-Sperre.
* Oberfläche (vitest): Vorauswahl, gesperrte Zeilen, Bestätigung vor erneutem Einzug, gleiche Vorgangskennung bei Wiederholung, Hinweis ohne Konto mit IBAN.
* Browser (Testversion, nach Upgrade `f4c6e8a0b2d3 → a5c7e9b1d3f5` mit geprüftem Vollbackup): falsche IBAN im Mieterformular abgelehnt, richtige gespeichert; Dialog mit Miete 680,00 € für MV-2020-010 und Hinweisen bei MV-2022-007; Datei heruntergeladen und gegen das Schema gültig; beim zweiten Öffnen markiert und Gläubiger-ID gemerkt; 390 px ohne Überlauf; keine Konsolen- oder Serverfehler.
