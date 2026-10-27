# TEHA: lokale Rückpakete und Folgeauftrag-Vorschau

Stand: 18. Oktober 2026. Empfang, explizite Zuordnung und atomare lokale
Übernahme bleiben auf dem bestehenden ConnectionRuns-/Archivpfad. Dieses
Paket ergänzt die Benutzung und lokale Vorbereitung; es führt keine
TEHA-Schreibaktion aus und verändert keine laufende Installation.

## Neue benutzbare Schritte

- Aus einer Dokumentverzeichniszeile wird der Originalempfang mit exakt
  empfangenem `lieg_nr` und `reference` vorbereitet. Erst der separate
  ausdrückliche Dispatch startet den lesenden Provideraufruf.
- Eine Periodenzeile bereitet ihr Dokumentverzeichnis mit der empfangenen
  `liegenschaftenNummer` vor. Ein Techniktermin bereitet seinen Nutzerempfang
  mit **Termin-ID** und `liegenschaftsnummer` vor.
- Das erneute Öffnen eines schon aufbereiteten Laufs liefert dessen
  vorhandenen Checkpoint, ohne Einträge zu duplizieren. Das Fortschreiben
  benötigt weiterhin die aktuelle Batchrevision.
- Kosten-/Nutzerdatenpakete enthalten eingefrorene Kostenpositionen,
  überschneidende Mietverträge und minimale lokale Parteien-/Einheitenbezüge.
  Centbeträge und Summe werden dezimal dargestellt. Namen begründen keine
  externe Identitätszuordnung; lokale Nutzer bleiben ausdrücklich lokal.
- Ein publizierter Techniktermin kann eine optionale lokale
  **Folgeauftrag-Vorschau** aufnehmen: Auftraggebername/-Mail und ausdrücklich
  ausgewählte, bereits empfangene aktuelle Nutzer desselben Termins. Erledigte
  oder gelöschte Nutzer, veraltete Quellhashes, widersprüchliche Kennungen und
  fehlende Namen/Kontakte führen zu 422/409 mit korrigierbaren Hinweisen.
- Die Nutzerwahl ist seitenweise fortsetzbar und behält die Auswahl über
  Seitenwechsel. Es gibt keine künstliche 250-Nutzer-Gesamtgrenze für ein
  lokales Paket; HTTP-/Snapshotbudgets bleiben getrennte technische Grenzen.
- Lokale Pakete sind als JSON-Prüfexport herunterladbar. Das ist weder ein
  freigegebenes TEHA-Importformat noch ein Versand- oder Portalbeleg.

## Aktueller öffentlicher Nachweis

Der Integrator hat am 18.10.2026 ausschließlich anonym die Portalseite und
deren öffentliche Datei gelesen. Der bestehende statische Parser erfasste
**78 HTTP-Aufrufstellen**; fremder Programmcode wurde nicht ausgeführt.

- Quelle: `https://kunden.socs.ws/assets/index-CjRzd8_M.js`
- Umfang: 1.274.312 Bytes
- Last-Modified: 12.10.2026, 13:46:04 UTC
- SHA-256: `328ac6c642b9892e7604ee67cf4e3c0d83b0b5f8700795561ec01b7b94bfa618`
- Rohdatei, Katalog und Beobachtungsmetadaten bleiben unter dem ignorierten
  Verzeichnis `artifacts/teha-public-observation-20261018/`. Im Quellcode stehen
  nur ein relevanter, redigierter Auszug und ausdrücklich belegte Bindungen.

Belegt ist `POST /api/Auftrag/create-folgeauftrag` mit
`Altauftrag`, `AuftraggeberName`, `AuftraggeberMail`, `Nutzer` und den
Nutzerfeldern `Id`, `BewohnerName`, `Anmeldeart`, `Kontaktdaten`, `Zusatzinfos`.
Die konkrete Aufrufstelle übergibt für `Altauftrag` **auftrag.auftragNummer**,
nicht `terminId`. Für `update-anmeldedaten` werden Auftragsnummer und Termin-ID
getrennt übergeben. Aktive Anmeldearten sind Brief 0, Telefon 1, Mail 2, SMS 3;
Hausaushang 4, Über Kunde 5 und Ohne 10 sind im öffentlichen Client deaktiviert.
Bei `lfdNr != '000'` ist der Bewohnername erforderlich, bei 1/3 ein
Telefonkontakt und bei 2 eine gültige Mail. Auftraggebermail ist optional.

Die öffentliche Folgeauftrag-Oberfläche lädt ihre Auswahl über
`/api/Auftrag/{Auftragsnummer}/offene-nutzer`. Der bereits bestätigte lokale
Empfang liest `nutzerInAuftrag` über die **Termin-ID**. Die tatsächliche Gleichheit
der Nutzer-`id` in beiden Antworten ist noch nicht authentifiziert abgeglichen.
Die lokale Vorschau kennzeichnet deshalb auch diese konkrete Ziel-ID-Bindung
als unbestätigt; sie leitet keine Identitätsgleichheit aus Feldnamen ab.

Die Kostenpfade `save-betriebskosten`, `save-brennstoffkosten`,
`save-hausnebenkosten` und `save-nutzer` sind mit ihren direkten
Requestschlüsseln statisch belegt. Deren verschachtelte Positions-/Nutzerobjekte
werden hier **nicht** als vollständiges Laufzeitschema behauptet und nicht in
einen geratenen Portalbody umgewandelt. Der bestätigte Empfangsvertrag vom
02.10.2026 bleibt versioniert erhalten; neue öffentliche Evidenz ersetzt keine
bestätigten Empfangsdaten.

## Schutz, Revision und Wiederherstellung

Neue Snapshots verwenden `immomanager-teha-local-preparation/2` in der
vorhandenen unveränderlichen, verschlüsselten Tabelle `teha_return_drafts`.
Alte `/1`-Pakete bleiben lesbar. Eine neue Tabelle oder Migration ist nicht
erforderlich. Die bestehende Restoreprüfung validiert weiterhin Snapshot-Hash,
Verbindungsbindung, `external_write_enabled:false` und `portal_contract:null`.

Jedes Paket behält seinen ursprünglichen Snapshot-Hash. Liste und Download
ermitteln separat den aktuellen lokalen Prüfstatus: vollständiger Kosten- und
Vertragsinhalt, minimale Nutzer-/Einheitenstände, Mappingrevision, zugeordnete
Akten, aktuelle vollständige Empfangsfassung, ausgewählte Nutzerquellen und
Währung. Änderungen werden auch erkannt, wenn eine Reparatur `updated_at`
unverändert lässt. Fehlende lokale Quellen machen das historische Paket
sichtbar ungültig, ohne die gesamte Liste zu verbergen. Das identische bereits
bestätigte Vorbereitungskommando lässt sich auch nach lokalen Änderungen mit
seinem ursprünglichen Wiederholungsschlüssel wiederlesen.

Export benötigt Anmeldung, aktuelle installationsweite Portfoliorechte,
die bestehende Sichtbarkeit des zugrunde liegenden Empfangslaufs und den
angezeigten Snapshot-Hash. Nicht-Eigentümer sehen nur ihre eigenen Pakete.
Antworten sind `private, no-store`, Downloads zusätzlich `nosniff`.

## Neue API

| Route | Verhalten |
|---|---|
| `GET /teha/{connection}/evidence` | Herkunft, Hash, relevante belegte Pfade/Felder und offene externe Abnahme |
| `GET /teha/{connection}/items/{item}/follow-up-users` | Fortsetzbare aktuelle empfangene Nutzer des Techniktermins; Count ist ausdrücklich der Empfangsbestand |
| `POST /teha/{connection}/items/{item}/prepare-return` | Bestehender revisionsgebundener Befehl; optional `follow_up:{orderer_name,orderer_email,users:[{item_id,source_sha256}]}` |
| `GET /teha/{connection}/returns` | Unveränderte Snapshots plus aktuelle lokale Validierung |
| `GET /teha/{connection}/returns/{draft}/export?snapshot_sha256=...` | Hashgebundener lokaler JSON-Prüfexport einschließlich Evidenz und Validierung |

## Verbleibende externe Abnahme

Für einen Versand fehlen weiterhin nachgewiesene aktuelle Kontoberechtigungen,
der vollständige Laufzeitvertrag der jeweils gewählten Operation,
Fehler-/Idempotenzsemantik bei verlorener Antwort und ein tatsächlicher
Portalbeleg mit anschließendem fachlichem Ergebnisabgleich. Kosten-/Nutzerdaten
benötigen zusätzlich vollständige verschachtelte Feldverträge und bestätigte
externe Kennungen. Ein statisch sichtbarer Erfolgszweig `data.success` ist kein
beobachteter HTTP- oder fachlicher Erfolg. Die Transport-Read-Allowlist wurde
nicht erweitert. Es wurden keine Aufträge, E-Mails oder Provider-Schreibaktionen
gesendet und keine Zugangsdaten ausgegeben oder im Quellcode gespeichert.

Die fokussierten Tests verwenden synthetische Quellen und unabhängige
Testlaufverzeichnisse. Ergebnisse und genaue Laufverzeichnisse werden im
gemeinsamen Integrationsnachweis festgehalten; eine Testprüfung ersetzt keine
Portal-Schreibabnahme.

## Fokussierte lokale Prüfläufe

- Aktuelle neue Workflow-/HTTP-Fälle: **19 bestanden, 0 übersprungen**,
  `artifacts/pro-tests/teha-final-local-1018-memory-8f7d5ea2b19d430d807e7a0d85ca1021/`.
- SQL-Empfang/Publikation, Sicherheit, Rückpakete, Provider, Transport,
  Exchange-Beobachtung und Migration: **202 bestanden, 1 übersprungen**,
  `artifacts/pro-tests/teha-return-workflow-1018-sql-68c38de662014125adfb834291677f7e/`.
  Ausgelassen wurde ausschließlich die reentrante Rechteentzugsprobe für den
  Arbeitsspeicherpfad; die SQL-Rechteentzugsprobe ist enthalten. Der Lauf hat
  eigene SQLite-Datenbanken verwendet und ist keine PostgreSQL-Abnahme.
- Zusätzliche authentifizierte SQL-HTTP-/Rundungsfälle: **4 bestanden**,
  `artifacts/pro-tests/teha-return-http-1018-sql-1c2b4adbb8844f028db799f90174591f/`.
- TEHA-Frontend: **11 bestanden**; gezieltes ESLint und Ruff ohne Befund.

Jeder Python-Lauf enthält `input.json`, `result.json`, `pytest.log` und
`junit.xml` mit Quellhashes und isolierten Runtimepfaden. Die finalen neuen
Memory-Fälle prüfen zusätzlich die konkrete Warnung zur unbestätigten
Folgeauftrag-Nutzer-ID-Bindung und die Sichtbarkeitsprüfung vor dem
Hash-Mismatch-Fehler. Die breitere SQL-Matrix wurde vor diesen letzten
Kennzeichnungs-/Fehlerreihenfolge-Ergänzungen gestartet; ihre Quellhashes
bezeichnen exakt den dort geprüften Zwischenstand.
