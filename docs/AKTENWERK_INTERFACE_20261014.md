# Schnittstelle ImmoManager Pro ↔ Aktenwerk (DMS)

Stand 14.10.2026 · Vertrag `immomanager-aktenwerk/1`

ImmoManager Pro übergibt Dokumente mit allem, was es über sie weiß, an Aktenwerk:
- Verträge, Rechnungen, Abrechnungen, Protokolle, Schreiben und Bescheide aus dem Dokumentenarchiv;
- Belege, die an Buchungen hängen.

Zu jedem Dokument kommen Art, Datum, Bezug (Objekt, Einheit, Mieter, Vertrag), Beträge und die steuerliche Einordnung mit.

Es gibt zwei gleichwertige Wege:

1. **Exportpaket**: eine ZIP-Datei mit `manifest.json` und den Dateien, die Aktenwerk importiert. Dafür ist keine Verbindung nötig, und das Paket eignet sich auch als Steuerunterlage.
2. **Direkte Übergabe**: ImmoManager sendet ausgewählte Dokumente an eine laufende Aktenwerk-Instanz. Das geschieht nur auf ausdrücklichen Auftrag (Knopf oder Sammelaktion), nie automatisch.

Die Gegenrichtung, also Aktenwerk liest aus ImmoManager, läuft über dieselben Lese-Endpunkte (Abschnitt 4).

## 1. Einträge

Jeder Eintrag hat eine stabile `exchange_id`:

| Quelle | `exchange_id` | Art (`kind`) |
| --- | --- | --- |
| Dokument im Archiv | `immomanager:document:<dokument-id>` | aus dem Dokumententyp, siehe unten |
| Beleg einer Buchung | `immomanager:booking-receipt:<buchungs-id>` | `beleg` |

Ist ein Beleg schon als Dokument archiviert (gleiche Datei-Adresse), erscheint er nur einmal, und zwar als Dokument.

**Arten:** `vertrag`, `rechnung`, `beleg`, `abrechnung`, `protokoll`, `korrespondenz`, `bescheid`, `nachweis`, `bescheinigung`, `sonstiges`.

Zuordnung der Dokumententypen:

| Art | Dokumententypen |
| --- | --- |
| `vertrag` | Mietvertrag, Kündigung, Versicherung |
| `rechnung` | Rechnung, Handwerkerrechnung, sowie jedes Dokument, das einer Rechnung als Original zugeordnet ist (Rechnungseingang der Rechnungsprüfung) |
| `abrechnung` | Neben- und Betriebskostenabrechnung, Kautionsabrechnung |
| `protokoll` | Protokoll, Übergabeprotokoll, Abnahme- und Begehungsprotokolle der Projektakte |
| `korrespondenz` | Mahnung, Mahnschreiben |
| `bescheid` | Steuerbescheid |
| `nachweis` | Grundbuchauszug, Energieausweis |
| `bescheinigung` | Wohnungsgeberbestätigung |

### Manifest-Eintrag

```json
{
  "exchange_id": "immomanager:document:7f0c…",
  "kind": "rechnung",
  "title": "Rechnung Heizung 2025",
  "date": "2025-03-04",
  "references": {
    "property": {"id": "…", "name": "Bautzner Straße 61"},
    "unit": {"id": "…", "name": "WE 3"},
    "tenant": {"id": "…", "name": "Mia Muster"},
    "contract": {"id": "…", "name": "MV-7"}
  },
  "finance": {
    "currency": "EUR", "gross": "119.00", "net": "100.00", "vat_rate": "19.00", "vat": "19.00",
    "supplier": "Wärmemeister GmbH", "invoice_date": "2025-03-04", "invoice_number": "HZ-25-17", "invoice_id": "…"
  },
  "tax": {"relevant": true, "deductible": true, "category": "werbungskosten", "year": 2025},
  "tags": ["heizung"],
  "source": {"type": "document", "id": "…", "document_type": "Handwerkerrechnung"},
  "file": {
    "name": "Rechnung Heizung 2025__1a2b3c4d.pdf",
    "path": "files/rechnung/2025/Rechnung Heizung 2025__1a2b3c4d.pdf",
    "media_type": "application/pdf", "size": 48213, "sha256": "…"
  }
}
```

**Allgemeine Regeln**
- **Beträge** stehen als Dezimaltext mit zwei Nachkommastellen, nie als Gleitkommazahl. Ausgaben eines Belegs sind negativ (`"amount": "-48.50"`).
- **Bezüge:** Ein Dokument, das an einem Vertrag hängt, erbt Mieter, Einheit und Objekt dieses Vertrags.

**Steuer (`tax`)**
- Das Feld ist eine Einordnung für die Anlage V, keine Steuerberatung.
- `relevant` gilt für Rechnungen, Belege, Abrechnungen und Bescheide.
- `deductible` (Werbungskosten) gilt für Rechnungen und für Belege von Ausgaben, die keine Stornos sind.
- `category` ist `werbungskosten`, `einnahmen`, `nebenkosten`, `steuerbescheid` oder `null`.
- `year` ist das Jahr des Dokuments, des Rechnungs- oder des Buchungsdatums.

**Datei (`file`)**
- Das Feld steht nur im Exportpaket und bei der Übergabe.
- Archivierte Originale (Übergabeprotokolle, Mahnschreiben, Kautionsabrechnungen …) werden aus dem geprüften Archiv gelesen, nie aus einer gleichnamigen Datei.

## 2. Exportpaket

Aufruf: `GET /api/v1/aktenwerk/export?year=2025&deductible=true` (Filter wie in Abschnitt 4).

Inhalt der ZIP-Datei:
- **`manifest.json`:** `{"schema": "immomanager-aktenwerk/1", "generated_at": "…", "source": {"system": "ImmoManager Pro", "version": "…"}, "entries": […], "problems": […]}`.
- **`files/<art>/<jahr>/<titel>__<kurz-id>.<endung>`:** je ein Eintrag mit Datei.

Unter `problems` stehen Einträge, deren Datei nicht lesbar ist (fehlt, liegt außerhalb der Portfolios des Kontos, verweist auf keine gespeicherte Datei). Sie werden mit Grund genannt und nicht stillschweigend weggelassen.

**Aktenwerk sollte beim Import** die `exchange_id` als Fremdschlüssel speichern und `sha256` mit der Datei vergleichen. Dann legt ein zweiter Import desselben Pakets nichts doppelt an.

## 3. Direkte Übergabe: was Aktenwerk bereitstellen muss

Basisadresse und Token werden in ImmoManager unter **Schnittstellen → Aktenwerk** eingetragen. Das Token wird verschlüsselt gespeichert und in der API immer als `***` angezeigt. Pfade relativ zur Basisadresse:

### `GET /api/immomanager/v1/health`
Antwort `200` bei erreichbarem Dienst. ImmoManager prüft damit nur die Verbindung („Verbindung prüfen“) und überträgt dabei nichts.

### `POST /api/immomanager/v1/documents`
- **Format:** `multipart/form-data` mit zwei Teilen: `metadata` (JSON-Text, ein Manifest-Eintrag inklusive `file` und `"schema": "immomanager-aktenwerk/1"`) und `file` (der Dateiinhalt).
- **Kopfzeilen:**
  - `Authorization: Bearer <token>`, falls ein Token eingetragen ist;
  - `Idempotency-Key: <exchange_id>:<sha256>`, für dieselbe Datei immer derselbe Schlüssel.

Antworten:

| Antwort | ImmoManager wertet als |
| --- | --- |
| `201` (neu) oder `200` mit geprüftem Receipt | übergeben |
| `409` mit geprüftem Receipt | derselbe Originalinhalt liegt nachweislich bereits vor |
| `409` ohne passendes Receipt | **Konflikt**, keine erfolgreiche Übernahme |
| `200`/`201` ohne passendes Receipt, `202`, `408`, `5xx` oder Verbindungsabbruch nach POST | **Ausgang unklar**, vor Wiederholung extern abgleichen |
| `401`/`403` | Zugang abgelehnt (Token prüfen) |
| `413` / `415` / `422` | zu groß / Dateityp nicht angenommen / Metadaten nicht angenommen |
| andere eindeutige Ablehnung | Fehlschlag mit HTTP-Status |

**Seit 16.10.2026 verlangte Empfangsbestätigung:** Bei `200`, `201` und `409` muss Aktenwerk JSON `{"id":"<aktenwerk-id>","exchange_id":"<kanonische exchange_id>","sha256":"<hash der tatsächlich gespeicherten Bytes>"}` liefern. Alle drei Felder müssen vorhanden sein und exakt zur Anfrage passen. Eine HTTP-409-Antwort oder eine bloße Remote-ID beweist keine identischen Bytes. Eine bisherige Gegenstelle, die nur `{"id":"…"}` zurückgibt, ist **nicht kompatibel mit einer bestätigten Übernahme**, bis sie den Nachweis ergänzt. Alternativ ist eine erst zu spezifizierende **lesende** Statusabfrage mit denselben geprüften Identitäten erforderlich; ImmoManager erfindet dafür keinen Endpunkt.

Bei möglicher Annahme und fehlendem bestätigten Receipt gilt **nicht blind erneut senden**. Es ist zuerst in Aktenwerk anhand von Exchange-ID und SHA-256 zu prüfen, was tatsächlich gespeichert wurde. Die lokale Antwort trennt `sent`, `already_present`, `conflict`, `unknown` und `failed`; `unknown` ist kein endgültiger Fehler.

Jedes Dokument ist eine eigene Anfrage. Ein Fehlschlag hält die anderen nicht auf, und die Antwort nennt das Ergebnis pro Dokument.

**Sicherheit**
- Unverschlüsseltes `http://` ist nur im lokalen Netz zulässig: localhost, private IP-Adressen und Rechnernamen ohne Punkt oder mit `.local`, `.lan`, `.home`, `.internal`, `.fritz.box`. Außerhalb verlangt ImmoManager `https://`.
- Zugangsdaten in der Adresse werden abgelehnt.
- Die TLS-Prüfung lässt sich nur ausdrücklich abschalten (für selbst signierte Zertifikate im lokalen Netz).

## 4. Endpunkte in ImmoManager

Alle Endpunkte verlangen eine Anmeldung (Bearer-Token eines ImmoManager-Kontos) und liefern nur, was dieses Konto im eigenen Portfoliobereich sehen darf. Für einen lesenden Zugriff aus Aktenwerk eignet sich ein eigenes Konto mit der Rolle „Nur lesen“.

| Endpunkt | Zweck | Rechte |
| --- | --- | --- |
| `GET /api/v1/aktenwerk/status` | Nur `{"enabled", "configured", "ready"}`: ob eine Übergabe starten kann (für die Schaltflächen); keine Einstellungen, keine Verbindungsprüfung | lesen, auch mit Portfolio-Beschränkung |
| `GET /api/v1/aktenwerk/manifest` | Manifest ohne Dateien und ohne `generated_at` (gleiche Daten, gleiche Antwort), mit `counts` je Art (Vorschau, Abruf durch Aktenwerk) | lesen |
| `GET /api/v1/aktenwerk/export` | ZIP-Paket (Abschnitt 2) | lesen |
| `POST /api/v1/aktenwerk/send` mit `{"exchange_ids": [...]}` (1–200) | Übergabe an Aktenwerk (Abschnitt 3) | Eigentümer, Verwalter, Buchhaltung |
| `GET /api/v1/files/download?key=…` | einzelne Datei (bestehender Endpunkt) | lesen |

Filter für `manifest` und `export`:
- `kind` (mehrfach möglich);
- `year`;
- `property_id`;
- `tax_relevant=true`;
- `deductible=true`.

Unbekannte Arten werden mit `422` abgelehnt.

Antwort von `send`: `{"message": "2 an Aktenwerk übergeben, 1 fehlgeschlagen", "sent": 2, "failed": 1, "results": [{"exchange_id": "…", "status": "sent" | "already_present" | "failed" | "unknown" | "conflict", "aktenwerk_id": "…", "reason": "…"}]}`.

Ist Aktenwerk deaktiviert oder nicht eingerichtet, antwortet der Endpunkt mit `409` und sendet nichts. Jede Übergabe steht im Integrationsprotokoll mit den `exchange_ids`, aber ohne Dateiinhalt und ohne Token.

## 5. Oberfläche

- **Dokumente → „Aktenwerk …“:** Auswahl nach Jahr, Arten, „steuerlich relevant“ und „nur absetzbar (Werbungskosten)“, mit Vorschau. Danach „Exportpaket (ZIP)“ oder, wenn eingerichtet, „An Aktenwerk übergeben“. Größere Auswahlen übergibt der Dialog in Blöcken zu 200 und meldet ein gemeinsames Ergebnis.
- **Sammelaktionen** (sichtbar, wenn Aktenwerk eingerichtet und aktiv ist):
  - Dokumente: „An Aktenwerk übergeben“;
  - Buchungen: „Belege an Aktenwerk“, nur für Zeilen mit Beleg;
  - Rechnungen: „An Aktenwerk übergeben“, nur für Rechnungen mit Originaldokument.

## 6. Offen / abzustimmen mit Aktenwerk

- **Rückverweis:** Die von Aktenwerk vergebene `id` erscheint in der Antwort und im Protokoll, wird aber noch nicht am Dokument in ImmoManager gespeichert. Ein Link „in Aktenwerk öffnen“ braucht dafür ein eigenes Feld (Migration) und die URL-Form von Aktenwerk.
- **Ablagestruktur und Verschlagwortung** auf Aktenwerk-Seite: Ordner nach `kind`/`year`/Objekt sind ein Vorschlag, die Felder dafür stehen im Manifest.
- **Dokumente aus Aktenwerk in ImmoManager:** Aktenwerk kann den bestehenden Upload (`POST /api/v1/files/upload`, dann `POST /api/v1/documents` mit Bezug) nutzen. Einen eigenen Eingangsweg mit Dublettenprüfung über `sha256` gibt es noch nicht.
- **Schlüssel des Steuerjahres:** Für Rechnungen ist es das Rechnungsdatum, nicht das Zahlungsdatum. Für Überschussrechnungen nach Zuflussprinzip sollte Aktenwerk die zugehörige Zahlung (Buchung) nachziehen.


## Dauerhafter Übergabebeleg und optionaler Statusabgleich (Integration 16.10.2026)

Vor einem HTTP-Schreibaufruf speichert ImmoManager die kanonische Exchange-ID,
SHA-256 und die exakten Originalbytes verschlüsselt in einem dauerhaften Vorgang.
Ein bestätigter Erfolg wird bei Wiederholung aus diesem Beleg beantwortet. Nach
verlorener Antwort bleibt der Vorgang `unknown`; ein weiterer Aufruf sendet das
Original nicht erneut. Abweichende Originalbytes unter derselben Exchange-ID
verlangen eine neue Dokumentfassung. Ein Konflikt verlangt eine Prüfung der Gegenstelle.

Ein positiver Empfangsbeleg muss eine nichtleere `id`, die unveränderte
`exchange_id` und den exakten `sha256` bestätigen. Falls die Gegenstelle `status`,
`schema` oder einen zusätzlichen Dateihash liefert, müssen auch diese Werte mit
einer erfolgreichen Ablage und diesem Original übereinstimmen. HTTP 200/201/409
allein ist kein Ablagenachweis.

Der zusätzliche Schalter `receipt_status_supported` bleibt standardmäßig aus.
Er darf nur aktiviert werden, wenn die Gegenstelle ausdrücklich folgenden
Vertrag implementiert: `GET /api/immomanager/v1/documents/{URL-kodierte Exchange-ID}`
mit Queryparameter `sha256` liefert bei HTTP 200 denselben vollständigen
Empfangsbeleg. Eine Wiederholung eines unklaren Vorgangs nutzt dann ausschließlich
diesen lesenden Abgleich. Die Anwendung folgt keiner vom Server gelieferten
Status-URL. Dieser optionale Vertrag und eine reale Aktenwerk-Gegenstelle sind
mit den synthetischen Integrationstests nicht als live verifiziert bezeichnet.

Vollständige Datenbanksicherungen enthalten diese Vorgänge, Originalblöcke und
Schlüssel. Der Wiederherstellungsnachweis prüft ihre verschlüsselten Inhalte,
Quellhashes, Blockreihenfolge und vollständigen Originalhashes vor Freigabe der
wiederhergestellten Daten.
