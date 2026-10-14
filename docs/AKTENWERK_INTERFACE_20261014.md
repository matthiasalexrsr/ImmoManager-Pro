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
| `201` (neu) oder `200`, Text `{"id": "<aktenwerk-id>"}` | übergeben |
| `409` (dieser Schlüssel liegt schon vor) | „bereits vorhanden“, also Erfolg |
| `401`/`403` | Zugang abgelehnt (Token prüfen) |
| `413` / `415` / `422` | zu groß / Dateityp nicht angenommen / Metadaten nicht angenommen |
| sonst | Fehlschlag mit HTTP-Status |

Jedes Dokument ist eine eigene Anfrage. Ein Fehlschlag hält die anderen nicht auf, und die Antwort nennt das Ergebnis pro Dokument.

**Sicherheit**
- Unverschlüsseltes `http://` ist nur im lokalen Netz zulässig: localhost, private IP-Adressen und Rechnernamen ohne Punkt oder mit `.local`, `.lan`, `.home`, `.internal`, `.fritz.box`. Außerhalb verlangt ImmoManager `https://`.
- Zugangsdaten in der Adresse werden abgelehnt.
- Die TLS-Prüfung lässt sich nur ausdrücklich abschalten (für selbst signierte Zertifikate im lokalen Netz).

## 4. Endpunkte in ImmoManager

Alle Endpunkte verlangen eine Anmeldung (Bearer-Token eines ImmoManager-Kontos) und liefern nur, was dieses Konto im eigenen Portfoliobereich sehen darf. Für einen lesenden Zugriff aus Aktenwerk eignet sich ein eigenes Konto mit der Rolle „Nur lesen“.

| Endpunkt | Zweck | Rechte |
| --- | --- | --- |
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

Antwort von `send`: `{"message": "2 an Aktenwerk übergeben, 1 fehlgeschlagen", "sent": 2, "failed": 1, "results": [{"exchange_id": "…", "status": "sent" | "already_present" | "failed", "aktenwerk_id": "…", "reason": "…"}]}`.

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
