# TEHA: tatsächlich beobachteter Portalvertrag

Stand: 2. Oktober 2026. Quelle: normale Bedienung des autorisierten Kundenkontos unter `https://kunden.socs.ws` im integrierten Browser und lesende Untersuchung seiner Netzwerkanfragen. Diese interne Portalschnittstelle ist kein öffentlich zugesicherter API-Vertrag. Änderungen müssen erkennbar abgefangen werden.

Die Anmeldung, Liegenschaftsliste, Dokumentliste, eine Originalrechnung und Kundendienstaufträge wurden tatsächlich erfolgreich abgerufen. Es wurden keine Kosten, Nutzerdaten, Aufträge oder sonstigen fachlichen Angaben geändert oder eingereicht. Diese Datei enthält keine Zugangsdaten, Tokens, privaten Objektkennungen, Adressen oder Bewohnerdaten. Die folgenden Feldnamen stammen aus den echten Antworten; Tests dürfen daraus bereinigte synthetische Beispiele erzeugen.

## Anmeldung

`POST /api/user` antwortete mit HTTP 200. Der JSON-Request enthält `Mandant` als Zahl (im beobachteten Konto `1`), `Username` und `PasswordHash` als Zeichenketten. Trotz seines Namens enthält `PasswordHash` die unveränderte Passworteingabe; der Transport muss daher ausschließlich an die festgelegte HTTPS-Adresse erfolgen.

Die Antwort besitzt unter anderem `id`, `mandantId`, `name`, `vorname`, `nachname`, `email`, `accessToken`, `refreshToken`, `rollen` und `error`. Nachfolgende Portalaufrufe verwenden `Authorization: Bearer …`. Die tatsächliche Refresh-Operation und ihre Fehlersemantik wurden noch nicht beobachtet. Eine Implementierung darf deshalb keinen Refresh-Endpunkt erfinden. Bei abgelaufener Sitzung ist zunächst eine eindeutige erneute Anmeldung vorzusehen; dauerhafte Geheimnisse benötigen getrennte geschützte Speicherung. Antworten und Fehlermeldungen dürfen keinen Token oder Passwortinhalt protokollieren.

## Liegenschaften und Abrechnungsperioden

`GET /api/liegenschaften` antwortete mit HTTP 200 und den Schlüsseln `success`, `fehlermeldung`, `liegenschaften`.

Die Liste enthielt vier Periodendatensätze zu zwei verschiedenen Liegenschaften. Die Portaloberfläche gruppiert diese zu zwei Immobilien. Maßgeblich ist `liegId` mit den numerischen Feldern `id` und `abrechnungLaufendeNr`: Objekt und Periode sind getrennte Identitäten. Eine Periodenzeile darf keine neue lokale Immobilie erzeugen.

Weitere beobachtete Felder:

```text
liegenschaftenNummer, strasse, plz, ort, bezeichnung, status,
kmlStatus, abrechnungVon, abrechnungBis, hatNebenkosten,
hatHeizkosten, initDone, abrechnungErlaubt, kmlBestaetigtDatum,
leistung, ablesedateiKomplett, istGekuendigt, mieterportalEnabled,
aktuellePeriode, eaiEnabled, brennstoffe, brennstoffLeitungsgebunden,
nettoErfassen, vertragEnddatum, liegCo2Angaben
```

Eine automatische Zuordnung allein über Name oder Anschrift ist ungeeignet. Die lokale Objektzuordnung muss ausdrücklich bestätigt sein und je Anbieter-Verbindung gelten. Bestätigte Perioden benötigen eigene stabile Schlüssel.

## Dokumentarchiv und Originalinhalt

`POST /api/Liegenschaften/documents` mit JSON `{ "LiegNr": "…" }` antwortete mit HTTP 200 und `{ "documents": […] }`. Der beobachtete String `LiegNr` entspricht **`liegenschaftenNummer`**, nicht `liegId.id`. Diese beiden Referenzen dürfen nicht vertauscht werden.

Dokumenteinträge haben `reference` als Zeichenkette, `fileName`, `properties` und `attachments` als Liste. Im geprüften Archiv waren zwei Dokumente vorhanden. Beobachtete Metadaten in `properties`:

```text
Abrechnung_laufende_Nummer, Abrechnungszeitraum_bis,
Abrechnungszeitraum_von, Adresse, Auftragsnummer, Barcode,
Belegart, Belegdatum, Belegnummer, Bemerkung, CREATE_DATE,
CREATOR_USERNAME, Kundenname, Kundennummer, Liegenschafts_ID,
Liegenschafts_Nummer, Mandant, Mieter_ID, Nutzereinheit_ID,
Nutzereinheit_lfd_Nr, Ort, PLZ, Selbstabrechner_Liegenschafts_ID,
Selbstabrechner_Nummer, Status, VERSION, SA
```

`POST /api/Liegenschaften/document-content` mit `{ "Ref": "…", "LiegNr": "…" }` antwortete mit HTTP 200 und `{ "content": "…" }`. `content` ist Base64. Die tatsächlich geöffnete Rechnung ergab 79.072 Bytes mit `%PDF-` als Dateisignatur. Der Archivimport muss die Originalbytes und ihren SHA-256 bewahren und kann eine geprüfte Vorschau getrennt erzeugen.

Der beobachtete Dokumenttransport enthält keine Periodennummer im Request. Dokumentmetadaten müssen daher gegen Objekt und Abrechnungsperiode geprüft werden. Die Gleichheit von `properties.Liegenschafts_ID` mit der Inventar-ID wurde noch nicht allgemein verifiziert. Ungenaue oder widersprüchliche Bindungen bleiben im Importbereich; sie dürfen keine lokalen Originale anderer Objekte oder Finanzbuchungen erzeugen. Dateinamen sind Anzeigeinformationen und dürfen keine lokalen Pfade bestimmen.

## Kundendienst und Termine

`GET /api/auftrag` antwortete mit HTTP 200 und den Schlüsseln `success`, `fehlermeldung`, `auftraege`. Im beobachteten Konto war ein offener, terminierter Auftrag sichtbar. Eintragsschlüssel:

```text
mandantId, abrLfdNr, liegenschaftsnummer, auftragNummer,
art, subArt, statusId, terminId, istAktuellePeriode, terminVon,
terminBis, abrechnungBis, plz, ort, ortsteil, strasse,
fullLiegNummer, adresse, terminText, auftragsArt, statusText
```

Das gewöhnliche Aufklappen dieses Auftrags erzeugte `GET /api/Auftrag/{terminId}` und HTTP 200. Der tatsächliche URL-Wert entspricht **`terminId`**, nicht `auftragNummer`. Die Antwort besitzt `success`, `fehlermeldung`, `nutzerInAuftrag`; die Bewohner-/Einheitseinträge enthalten:

```text
id, neId, lfdNr, bewohnerName, eigentumer, kontaktdaten,
zusatzinfos, anmeldeart, geschoss, lage, geschossLageNr,
hauseingang, serviceterminId, zwischenablesung, anmeldung,
erledigt, deleted, wohnung
```

Auftrag, Servicetermin, lokale Einheit und Bewohner brauchen getrennte Zuordnungen. Eine Nutzerliste ist kein Beleg dafür, dass ein Auftrag bereits abgeschlossen ist. Terminänderungen dürfen nur offene lokale Projektionen anpassen; bestätigte abgeschlossene Fakten bleiben erhalten.

## Grenzen dieser Untersuchung und nächste Umsetzung

Noch ungeprüft sind Sitzungserneuerung, echte Ausfälle/Rate-Limits, große Anbieterdatenbestände, Pagination, zusätzliche Dokumentarten/Anhänge, Einreichung von Kosten-/Nutzerdaten und Restarbeitsaufträgen. Die beobachteten kompletten Listen besitzen keinen nachgewiesenen Cursor. Ein Adapter darf keine erfundene Pagination oder stilles Abschneiden der ersten Datensätze verwenden.

Der lesende, gekapselte HTTP-Transport ist inzwischen als eigene Einheit implementiert und synthetisch mit 110 fokussierten Fällen geprüft. Root hat anschließend genau diesen Programmcode gegen das autorisierte Portal ausgeführt: Anmeldung erfolgreich, vier Perioden zu zwei Objekten, Dokumentliste und Originalabruf erfolgreich, ein Technikauftrag und dessen Nutzerdetail erfolgreich. Die 79.072 Originalbytes entsprechen exakt dem SHA-256 des vorher im Browser beobachteten PDFs. Nach dem Schließen ist die Programmsitzung entfernt. Zugangsdaten wurden verdeckt im Terminal eingegeben; weder Datei noch Quellcode noch Ergebnisprotokoll enthält sie. Private Providerwerte wurden im Ergebnis nicht ausgegeben.

Diese Liveprobe belegt den Programmtransport, noch keinen vollständigen Benutzerablauf in der Verwaltungssoftware. Dauerhafte Verbindung, Objekt-/Periodenzuordnung, Wiederanlaufjournal, geschützte Importvorschau, bestätigter Originalimport und Recovery stehen noch aus. Erst der gemeinsam geprüfte vollständige Ablauf wird als nutzbare TEHA-Anbindung ausgewiesen.

## Ergänzende Adapterfreigabe des Eigentümers

Der Eigentümer hat im laufenden Chat ausdrücklich erlaubt, dass alle Adapter sämtliche auffindbaren Schnittstellen, Parameter und Werte extrahieren dürfen. Die Untersuchung erfasst deshalb auch zusätzliche, bislang fachlich unbekannte Antwortfelder und bewahrt private Quellsnapshots für spätere Zuordnung. Ein gemeinsamer Schema-Beobachter erfasst alle Arrayzeilen und Feldtypen ohne erste-100-Stichprobe. Seine Feldpfade können selbst private Kennungen enthalten und werden entsprechend geschützt.

Gefundene Schnittstellen werden nach tatsächlichem Beleg erfasst, nicht als automatisch ausführbare Schreibbefehle freigegeben. Zugangsdaten und Tokens bleiben außerhalb fachlicher Snapshots und allgemeiner Protokolle. Vor einer zusätzlichen Übertragung werden die konkrete Operation, Objekt-/Periodenbindung, Vorschau und tatsächliche Rückmeldung geprüft.
