# TEHA: lesender Transport, erste Umsetzungseinheit

Stand: 2. Oktober 2026. Basis: `bd165e897ab9fe0748b7ff28c6c5cef0a77fee5c`. Diese Einheit ist ein isolierter Transportbaustein mit bereinigten Tests. Sie ist noch keine im Produkt eingerichtete TEHA-Anbindung und wurde nicht mit echten Zugangsdaten ausgeführt.

## Implementiert und tatsächlich beobachtete Grundlage

`backend/services/providers/teha_transport.py` verwendet das bereits vorhandene `httpx`; keine neue Abhängigkeit. Import und Konstruktion lösen keinen Netzaufruf aus. Der Root-Agent hat die zugrunde liegenden Formen im autorisierten Portal tatsächlich beobachtet; alle Testwerte sind künstlich.

| Methode des Bausteins | Festgelegter Portalrequest | Ergebnis |
| --- | --- | --- |
| `authenticate(username, password)` | `POST /api/user`, `{Mandant: 1, Username, PasswordHash}` | Accountidentität und sitzungsgebundene Tokens ausschließlich im Speicher. `PasswordHash` bekommt die unveränderte Passworteingabe, entsprechend dem Livebeleg. |
| `list_property_periods()` | `GET /api/liegenschaften` | Vollständige Periodenliste mit getrennter numerischer Objekt-/Periodenidentität. |
| `list_documents(lieg_nr)` | `POST /api/Liegenschaften/documents`, `{LiegNr}` | Vollständige Liste, Referenz und Anzeige-Dateiname, private Metadaten/Attachments. |
| `read_document(lieg_nr, reference)` | `POST /api/Liegenschaften/document-content`, `{Ref, LiegNr}` | Streng dekodierte originale PDF-Bytes, tatsächlicher SHA-256 und Bytezahl. |
| `list_technical_orders()` | `GET /api/auftrag` | Aufträge mit getrennter `terminId`, `auftragNummer` und Periodenreferenz. |
| `read_order_users(termin_id)` | `GET /api/Auftrag/{terminId}` | Nutzer-/Einheitsidentitäten; private Rohinformationen. |

Die festgelegte Origin ist `https://kunden.socs.ws`, TLS-Prüfung aktiv, Umgebungsproxy/Netrc abgeschaltet, Redirectfolge abgeschaltet. Zusätzlich prüft die interne Requestmethode eine feste Method-/Pfad-Allowlist; absolute/fremde URLs, Queries, erfundene Refreshpfade und fachliche Schreibpfade scheitern vor einem Request. Die zwei dokumentierten Dokument-POSTs lesen Daten. Es gibt keine generische externe Requestaktion.

`liegId.id` und `abrechnungLaufendeNr` bleiben getrennt. `LiegNr` ist eine Zeichenkette und entspricht der beobachteten `liegenschaftenNummer`; dieser Transport leitet daraus noch kein internes Mapping ab. Der Auftragdetailpfad nutzt ausschließlich die beobachtete numerische `terminId`, nicht die Auftragsnummer. Dokumentproperties enthalten numerisch aussehende Strings; sie werden nicht blind auf die Inventar-ID umgedeutet. `serviceterminId` war im Nutzerdatensatz null; sein künftiger Typ wird nicht erraten.

Im Livebeleg war der einzige Auftrag terminiert und seine drei Datumsfelder waren Strings. Nicht terminierte Aufträge und mögliche null-Datumsfelder sind bislang unbestätigt. Der erste Vertrag nimmt ihre Semantik nicht vorweg: eine solche neue Form wird sicher als Schemaänderung abgefangen und braucht einen zusätzlichen bereinigten Livebeleg mit Adaptererweiterung.

## Öffentliche Daten und sichere Fehler

`teha_types.py` enthält getrennte DTOs. Private Providerquellen sind nur über explizite Snapshotmethoden verfügbar und fehlen in `repr`/`str`. Snapshotrückgaben sind tiefe Kopien. Accountantworten behalten absichtlich ausschließlich Account-/Mandantenidentität; unbekannte Loginantwortfelder und ursprüngliche Login-JSON werden nicht gespeichert. Access-/Refresh-Token und Cookies werden bei `close()` vollständig aus den Transportattributen entfernt; ein Ersatzlogin räumt die alte Identität vorher auf und scheitert ohne Restanmeldung. HTTP 401 entfernt die Sitzung und verlangt eine klare erneute Anmeldung. Es wird kein Refreshendpunkt angenommen und keine automatische Login-/Requestschleife gestartet.

`TehaError` enthält einen statischen sicheren Code, `retryable`, optional `retry_after_seconds` und `http_status`. HTTPX-Ausnahmetexte, Providerfehlermeldungen, Rohantworten, Passwort/Token und Redirectziele werden nicht übernommen. 429 und vorübergehende Server-/Netzwerkfehler sind als wiederholbar gekennzeichnet; `Retry-After` wird als Sekunden oder HTTP-Datum normalisiert. Tatsächliche Wiederholung gehört später in den dauerhaften Job, nicht in eine verborgene Transportschleife. 403 bleibt eine Berechtigungsablehnung und löst keine neue Anmeldung aus.

JSON muss ein eindeutiges UTF-8-Objekt sein; doppelte Schlüssel, nichtendliche Werte, falsche Erfolgstypen, HTML200 und beschädigte Pflichtidentitäten ergeben klare Fehler. Authentifizierung erfordert das tatsächlich vorhandene Feld `error` mit null beim Erfolg sowie eine strikt numerische Account-ID. Explizites `success=false` wird auch bei ansonsten gültigen optionalen Dokumentantworten nicht als Erfolg akzeptiert. Base64 wird strikt und kanonisch geprüft. Das erste bestätigte Originalformat ist PDF; unbekannte andere Inhalte werden als `provider_document_not_pdf` abgefangen, ohne sie falsch als PDF zu archivieren. Dateinamen bleiben Anzeigenamen; dieser Baustein schreibt keinerlei lokale Datei.

## Budgets und ausdrücklich verbleibende Grenzen

Konfigurierbare positive `max_response_bytes`, `max_document_bytes`, `timeout_seconds` und `response_deadline_seconds` begrenzen technische Arbeit je Operation. Es gibt kein Datensatz-, Objekt-, Perioden- oder Dokumentanzahllimit und keine Abschneidung auf die ersten 100/200 Zeilen. Der vollständige Inventarabruf wird zurückgegeben; echte Providerpagination oder Deltaabfrage ist nicht belegt und wird nicht erfunden.

Responsebytes werden bei HTTPX-Streaming gezählt, ein vorhandener Content-Length zusätzlich vorgeprüft. JSON wird nach dem budgetierten Empfang zusammengefügt und geparst; die DTO-Liste materialisiert die vollständige Antwort. Dies ist kein Nachweis konstanten Speichers bei beliebig großem Anbieterinventar. Die Folgestufe soll große lokale Arbeitslisten cursorbasiert verarbeiten und bei Bedarf den Transport um einen geprüften inkrementellen JSON-Parser erweitern.

Der Client fordert `Accept-Encoding: identity` an. Falls der Anbieter trotzdem eine unterstützte Komprimierung sendet, zählt das Bytebudget die dekomprimierten Nutzdaten. HTTPX kann dabei einen komprimierten Chunk vor unserer Zählung dekomprimieren; dieses Budget ist deshalb kein harter Schutz gegen jede Decoder-Peakallokation. Ebenso ist die Response-Deadline ein kooperatives Zeitbudget zwischen eintreffenden Chunks. Ein gerade blockierender Socket kehrt spätestens nach seinem separaten Sockettimeout zurück; ein harter identischer Gesamt-Walltime-Abbruch wird nicht behauptet.

Datumsstrings bleiben unverändert; keine Zeitzone des Servers oder Windowsrechners wird ergänzt. `parse_naive_iso_datetime()` bietet eine optionale ausdrückliche Umwandlung für das tatsächlich beobachtete naive ISO-Format und verweigert eine zusätzliche Zeitzone oder unbekanntes Format. Deutsche Dokumentdatumsstrings bleiben in den privaten Originalproperties und brauchen später ihre eigene bestätigte Konvertierung.

## Validierung dieser Einheit

- 110 fokussierte Tests bestanden, einschließlich der sechs tatsächlichen Requestformen, vier Periodenzeilen zu zwei Immobilien, voller Liste mit 10.007 Zeilen, unveränderter PDF-/Hashausgabe und bewahrten unbekannten Feldern.
- Negative Fälle: numerische ID-/Booleanverwechslung, falsche Shapes, HTML200/ungültiges JSON, Providerfailure, Authwechsel/401, fehlende Anmeldung, 403/429/503, Timeouts, fremde Redirects und interne absolute URL/Pfadmanipulation, Base64/PDF-Signatur, Response-/Dokumentbudgets einschließlich Streaming und dekomprimiertem Inhalt.
- Ruff für alle drei Providerdateien und die fokussierte Testdatei erfolgreich.
- Mypy für dieselben vier Dateien mit Linux/Python 3.11 und Windows/Python 3.12 erfolgreich.
- Unabhängiger Read-only-Review: der gefundene interne Origin-Fallstrick wurde durch die feste Allowlist behoben und mit zusätzlichen synthetischen Fremdurl-/Traversal-/Query-Repros unabhängig bestätigt; keine weiteren blockierenden Befunde im Transportumfang.

Keine echten Zugangsdaten, Tokens, Immobilienkennungen, Bewohnerdaten oder Originaldokumente befinden sich in Code oder Fixtures.

## Was Root anschließend integrieren muss

Geschützte Verbindungs-/Credentialverwaltung, dauerhafte Objekt-/Periodenmappings, eigene Empfangsjobs mit Claims/Revision/Restart, autorisierter Inboxspeicher und Vorschau, ausdrückliche Originalfreigabe über vorhandene Dokumentversionschunks, Fresh-Role-/Portfolio-Prüfung, UI, Migration/Legacyupgrade/Recovery/Teiltransferschutz und tatsächlicher fertiger Programmablauf gegen das Portal.

Ein Transportobjekt gehört einem einzelnen Lauf/Akteur und ist kein globaler Mehrbenutzer-Singleton. Alle Requestmethoden sind synchron; lange Requests nicht unter vorhandenen Datenbank-/operativen Singleton-Locks ausführen. Exceptions müssen vom fachlichen Job in sichere sichtbare Wiederaufnahmezustände übersetzt werden. `source_snapshot()` enthält private Daten und darf nicht ungefiltert als allgemeine Integrationshistorie oder UI-Response veröffentlicht werden.

Auftrags-/Nutzerstatus liefert Beobachtungen, keinen automatischen lokalen Vertrags-, Mieter- oder Projektstatus. Interne Rollen werden nicht aus Anbieterrollen abgeleitet. Kosten-/Nutzerübermittlung und Restarbeitsaufträge sind hier bewusst kein implementierter Fachvertrag. Die tatsächliche Programmanbindung gilt erst nach den fehlenden Produkt-/Recovery-/Liveabnahmen als fertig.
