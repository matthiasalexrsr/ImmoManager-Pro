# ADR-Entwurf: TEHA-Empfang und wiederaufnehmbare Portal-Anbindung

Stand: 2. Oktober 2026. Read-only-Analyse der Integration `work/root-correspondence-integration`, Stand `68256f4` plus Root-Livebeobachtungen vom gleichen Tag. Dieses Dokument ist ein Implementierungsentwurf, kein Nachweis eines bereits eingebauten Adapters. Es enthält weder Zugangsdaten noch Objektadressen oder Dokumentinhalte.

## 1. Entscheidung

TEHA erhält einen kleinen versionsgebundenen HTTP-Adapter, eine eigenständige fachliche Anbindung und dauerhafte SQL-Journale. Der vorhandene Integrationsmanager bleibt die Katalog-/Statusfassade. Seine synchrone `run()`-Methode und seine flüchtige Historie werden nicht zur Quelle der Wahrheit für den TEHA-Abgleich.

Die erste praktisch nutzbare Strecke lautet: geschützte Verbindung einrichten → Portalbestand abrufen → Objekte und Perioden bewusst zuordnen → Dokumente und technische Aufträge lesend empfangen → lokale Vorschau → Dokumentoriginale freigeben → Folgeläufe fortsetzen und nachweisen. TEHA-Schreiboperationen folgen als gesonderte, tatsächlich beobachtete Fachbefehle; ihre Existenz wird aus den Leseendpunkten nicht abgeleitet.

Der eigene Browserzugriff ist hier ein Belegwerkzeug. Der Produktionsserver soll für die beobachtete HTTP-Strecke keinen geöffneten Browser und keine angemeldete ChatGPT-Sitzung benötigen.

## 2. Was tatsächlich belegt ist

Die folgenden Belege wurden vom Root-Agent am autorisierten Konto beobachtet und an diesen Entwurf übermittelt. Ich selbst habe weder Portal noch Zugangsdaten geöffnet.

| Beobachtung | Beleg | Aussagegrenze |
| --- | --- | --- |
| Gewöhnliche Portal-Anmeldung | Erfolgreich auf `https://kunden.socs.ws`; `POST /api/user` HTTP 200 mit `{Mandant: 1, Username: string, PasswordHash: string}` | `PasswordHash` enthält trotz Name die unveränderte Passworteingabe. Antwort liefert `accessToken` und `refreshToken`; folgende Requests verwenden Bearer. Refreshverfahren, Ablaufzeiten und weitere Loginzustände noch unbestätigt. |
| `GET /api/liegenschaften` | HTTP 200; Objekt mit `success`, `fehlermeldung`, `liegenschaften` | Vier Inventarzeilen entsprechen zwei unterschiedlichen Immobilien mit mehreren Abrechnungsperioden. Keine beobachtete serverseitige Pagination, Delta-API oder garantierte Sortierung. |
| Identität einer Inventarzeile | `liegId` mit numerischen `id` und `abrechnungLaufendeNr`; zusätzlich `liegenschaftenNummer` | Objekt und Periode müssen getrennt werden. Dauerhafte Identität und Verhalten bei Umnummerierung bleiben zu prüfen. |
| Dokumentliste: `POST /api/Liegenschaften/documents` | HTTP 200; Request `{LiegNr: string}`; `LiegNr` entspricht exakt `liegenschaftenNummer`, nicht `liegId.id` | POST ist hier eine beobachtete Leseoperation. Daraus folgt keine generelle Freigabe aller POST-Pfade. |
| Dokumentliste-Antwort | `{documents: [...]}`; zwei Dokumente; je `reference: string`, `fileName`, `properties`, `attachments: array` | Bedeutung und Downloadpfad von Attachments sowie maximale Listenlänge bleiben zu prüfen. |
| Dokumentinhalt: `POST /api/Liegenschaften/document-content` | HTTP 200; Request `{Ref, LiegNr}`; Antwort `{content: string}` | `content` ist beobachtet Base64; ein Original ergibt 79.072 Bytes und beginnt mit `%PDF-`. Dies belegt ein tatsächliches PDF, nicht pauschal alle Dateitypen. |
| Technikauftrag-Inventar: `GET /api/auftrag` | HTTP 200; `{success, fehlermeldung, auftraege}` mit einem offenen Technikauftrag | Termin-/Statuswerte sind beobachtet, Änderungs- und Projektionssemantik bleibt gesondert festzulegen. |
| Nutzer-/Technikdetail: `GET /api/Auftrag/{terminId}` | HTTP 200; URL-ID entspricht exakt `terminId`, nicht `auftragNummer`; `{success, fehlermeldung, nutzerInAuftrag}` | Die Liste enthält personenbezogene Nutzer-/Einheits-/Kontaktinformationen und darf deshalb nicht wie ein öffentliches Technikerverzeichnis behandelt werden. |

Beobachtete Dokumenteigenschaften: `Abrechnung_laufende_Nummer`, `Abrechnungszeitraum_bis`, `Abrechnungszeitraum_von`, `Adresse`, `Auftragsnummer`, `Barcode`, `Belegart`, `Belegdatum`, `Belegnummer`, `Bemerkung`, `CREATE_DATE`, `CREATOR_USERNAME`, `Kundenname`, `Kundennummer`, `Liegenschafts_ID`, `Liegenschafts_Nummer`, `Mandant`, `Mieter_ID`, `Nutzereinheit_ID`, `Nutzereinheit_lfd_Nr`, `Ort`, `PLZ`, `Selbstabrechner_Liegenschafts_ID`, `Selbstabrechner_Nummer`, `Status`, `VERSION`, `SA`.

Die Feldnamen liefern Kandidaten für Zuordnungen. Ihre Übereinstimmung mit Inventar-IDs, Datentypen, Nullwerten und Perioden ist vor einem automatischen Import zu prüfen. Namen, Straße und Dateiname werden niemals zu einer Identitätsregel.

Beobachtete Authantwortfelder außer Tokens: `id`, `mandantId`, `name`, `vorname`, `nachname`, `email`, `rollen`, `error`, `isSelbstabrechner`, `isAdministrator`, `isTeamleiter`, `isAbrechner`, `isDisponent`, `isArtikelpflege`, `isVertrieb`, `salesBerechtigungen`, `isVertragsverwaltung`, `primaereRolle`, `isTicketBearbeiter`, `isTicketAdmin`, `franchisepartnerId`. Externe Anbieterrollen ersetzen keine internen Verwaltungsrollen oder Portfoliogrenzen.

Beobachtete Auftragfelder: `mandantId`, `abrLfdNr`, `liegenschaftsnummer`, `auftragNummer`, `art`, `subArt`, `statusId`, `terminId`, `istAktuellePeriode`, `terminVon`, `terminBis`, `abrechnungBis`, `plz`, `ort`, `ortsteil`, `strasse`, `fullLiegNummer`, `adresse`, `terminText`, `auftragsArt`, `statusText`.

Beobachtete Nutzer-im-Auftrag-Felder: `id`, `neId`, `lfdNr`, `bewohnerName`, `eigentumer`, `kontaktdaten`, `zusatzinfos`, `anmeldeart`, `geschoss`, `lage`, `geschossLageNr`, `hauseingang`, `serviceterminId`, `zwischenablesung`, `anmeldung`, `erledigt`, `deleted`, `wohnung`.

## 3. Verwendbare und ungeeignete vorhandene Bausteine

| Datei | Befund und Konsequenz |
| --- | --- |
| `backend/services/integrations/base.py` | `IntegrationManifest`, `IntegrationProvider`, `IntegrationActionResult` eignen sich für Katalog, Konfiguration und delegierte Statusanzeige. TEHA-Operationen dürfen zusätzlich einen fachlichen Batch-/Job-Identifier liefern. |
| `backend/services/integrations/manager.py` | `_history` ist eine prozesslokale Liste und wird nach 200 Einträgen gekürzt. `get_integration()` ruft `health()` beim Lesen auf. TEHA-Historie darf daher nicht hier gespeichert werden; `health()` darf keinen Portal-Login bei jeder Seitenanzeige auslösen. |
| `backend/services/integrations/config_store.py` | Gute kooperierende Dateisperre, atomare Veröffentlichung und Validierung. Die JSON-Datei verschlüsselt Secrets jedoch nicht; Maskierung erfolgt nur in Antworten. Geeignet für kleine öffentliche Konfiguration, nicht für TEHA-Zugangsdaten, Tokens oder fachliche Inventare. |
| `backend/db/document_version_models.py` | Unveränderliche Originalmanifeste, Hash, Größen, Subjekt-/Portfoliozuordnung und 64-KiB-Blöcke sind direkt nutzbar. Kein zweites Originalarchiv erfinden. |
| `backend/services/document_versions.py` | `persist_version_bytes()` arbeitet in der Transaktion des Aufrufers und kann streamingfähige Blocks übernehmen. `publish_generated_original()` ist ausdrücklich für erzeugte PDFs, erwartet komplette Bytes und setzt einen generated-Kommentar: keinen fremden Portalbeleg als generated-PDF deklarieren. Ein schmaler Publisher für importierte Originale soll denselben manifest-/chunkfähigen Kern nutzen. |
| `backend/services/outbox.py`, `outbox_state.py` | Bewährte persistente CAS-/Claim-/Lease-/Fencing-/Idempotenzmuster. Netzwerk erfolgt außerhalb der Datenbanktransaktion. TEHA-Lesejobs benötigen eigene Zustände; SMTP-`DATA` und unklare Zustellung sind dafür kein passendes Fachmodell. |
| `backend/services/operational_schedule.py` | Wiederholungen, lokale Kalenderprojektion und deduplizierte Benachrichtigungen vorhanden. Der globale Tick ist keine allgemeine Queue für lange Netzwerkarbeit. TEHA-Abfragen nicht unter dem operativen Singleton-Lock ausführen. |
| `backend/services/portfolio_scope.py` | Frische Benutzer-/Portfolio-Grenzen und SQL-Prädikate vorhanden. Fachliche neue Tabellen mit explizitem `portfolio_id` integrieren; Secrets und unzugeordnete Accountinventare brauchen zusätzliche spezielle Zugriffskontrollen. |
| `backend/services/iban_encryption.py` | Unabhängiges Verschlüsselungs-Keyring und sichere Fehler vorhanden. IBANs verwenden absichtlich deterministisches AES-SIV mit fachlichem Kontext. Zugangsdaten brauchen eigene Kryptografie-Domäne und dürfen nicht über `encrypt_iban()` verschlüsselt werden. |
| `backend/services/full_recovery.py`, `recovery_validation.py` | Vollbackup enthält Datenbank, Uploads und explizite Konfiguration; prüft vor Restoreveröffentlichung. Neue Journale und ihre Geheimnisse müssen in dieser Vorprüfung validiert werden; ältere vollständige Images ohne das komplette neue Modul bleiben lesbar. |
| `scripts/private_server_backup.py`, `restore_session_security.py` | Privater PostgreSQL-/Appdata-Backup und Signerschlüsselrotation vorhanden. ENCRYPTION-Keyring-Felder sind bereits im erlaubten Serverkonfigurationssatz. Neue Provider-Schlüssel oder Worker-Konfiguration explizit ergänzen, wenn sie neu eingeführt werden. |
| `backend/services/data_transfer.py` | Teiltransfer ist ausdrücklich kein vollständiges Recovery. Existierende Retentionsfamilien verweigern Ersetzen, wenn der Transfer ihre Historie verlieren würde. TEHA muss ebenso geschützt werden. |
| `frontend/src/pages/Integrations.jsx` | Heute Katalog, Toggle und ein Testlauf. Für eine nutzbare TEHA-Anbindung sind Verbindung, Objektzuordnung, Empfangsvorschau und Jobstatus erforderlich; ein zusätzlicher Testknopf genügt nicht. |

## 4. Codeaufteilung

Vorgeschlagene neue Dateien, an endgültige P1-Infrastruktur anzupassen:

- `backend/services/providers/teha_transport.py`: nur HTTP-/Authentifizierung-/Schema-Übersetzung; keine Store- oder UI-Abhängigkeit. Öffentliche Methoden `authenticate`, `list_property_periods`, `list_documents`, `read_document`, `list_technical_orders`, `read_order_users(termin_id)` auf genau die beobachteten Strecken begrenzen. Refresh und weitere Technikmethoden erst nach tatsächlichem Livebeleg ergänzen.
- `backend/services/providers/teha_types.py`: explizite Adapter-Datentypen einschließlich Herkunft, Identitäten, unveränderter Providerfelder und sicherer Fehlercodes.
- `backend/services/provider_connections.py`: autorisierte Konfiguration und Geheimnisänderung; öffentliche Darstellung ohne Secret oder ungemappte Kontodaten.
- `backend/services/provider_sync.py`: dauerhafte Jobs, Claims, Cursor, Wiederaufnahme, zugeordneter Empfang und lokale Veröffentlichung.
- `backend/services/provider_validation.py`: pure Journal-/Mapping-/Original-/Secret-Prüfungen für Laufzeit und Recovery.
- `backend/services/provider_secret_encryption.py`: Geheimnishülle mit fachlichem Kontext und Key-ID; keine JWT-Abhängigkeit.
- `backend/db/provider_models.py`, `backend/provider_models.py`: ORM und getrennte HTTP-Kommandos/Responses.
- `backend/routers/providers.py`: explizite fachliche API, nicht frei übergebenes Provider-`payload`.
- `backend/services/integrations/teha.py`: dünne Katalogfassade; delegiert zur Verbindung, liefert nur lokalen Gesundheitsstatus.
- `frontend/src/components/TehaConnection.jsx`, `TehaPropertyMappings.jsx`, `TehaSyncInbox.jsx`: Konfiguration, Zuordnung, Empfang und Fortsetzen im vorhandenen Integrationsbereich; Details zusätzlich auf der Immobilie.

Registrierung und Schutz gehören in `backend/db/session.py`, `backend/db/migrations/env.py`, `backend/routers/__init__.py`/Router-Wiring, `backend/permissions.py`, `backend/services/portfolio_scope.py`, Memory-Collections/Clone/Reset in `backend/storage.py`, SQL-Reset in `backend/repositories/sql_store.py`, `backend/services/data_transfer.py` und sämtliche echten Recoverypfade. Die neue Alembicrevision wird auf den tatsächlichen dann aktuellen Head gesetzt; parallel laufende P1-Migrationen nicht durch einen geratenen `down_revision` umgehen.

## 5. Identitäten und Mindestdatenmodell

Eine Verbindung ist im ersten Schritt genau einem internen Portfolio zugeordnet. Dadurch bleiben Daten-/Jobgrenzen klar. Mehrere Portfolio-Verbindungen zum selben Anbieteraccount dürfen dieselbe verschlüsselte Credentialreferenz verwenden, benötigen aber getrennte Zuordnungen und Journalbereiche. Eine übergreifende Installationsebene muss ausdrücklich eingeführt werden, wenn dieser Anwendungsfall benötigt wird.

### `provider_connections`

`id`, `portfolio_id`, `provider='teha'`, `adapter_version`, `base_origin`, `enabled`, `revision`, `credential_ref`, `auth_generation`, `sync_actor_id`, `created_by`, `last_checked_at`, `last_success_at`, `status`, `last_error_code`, `created_at`, `updated_at`. Auflistungen liefern keine Zugangswerte. Die Origin ist als Anbieterstandard festgelegt; eine administrativ konfigurierbare abweichende Origin braucht einen absichtlich geprüften Anbieterwechsel, keine beliebige Formular-URL.

### `provider_credentials`

`id`, `portfolio_id`, `connection_id`, `revision`, `key_id`, `encrypted_secret`, `created_at`, `updated_at`. Geheimnisinhalt enthält Benutzername und Passwort; je nach Live-Authentifizierungsvertrag Tokens nur bei begründetem Bedarf dauerhaft speichern. Bevorzugt kurze Access-Tokens pro Lauf im Speicher; Loginserien und Sperrverhalten beachten. Keine automatische Authentifizierungs-Endlosschleife.

### `provider_object_mappings`

`id`, `portfolio_id`, `connection_id`, `external_object_id`, `internal_property_id`, `revision`, `state`, `confirmed_by`, `confirmed_at`, `source_identity_snapshot`, `created_at`, `updated_at`.

Eindeutig `(connection_id, external_object_id)`; eine aktive interne Immobilie pro gewollter Anbieterzuordnung. `external_object_id` wird aus dem beobachteten numerischen `liegId.id` verlustfrei normalisiert. Ein Dokumenttransport wird separat mit der exakt beobachteten `liegenschaftenNummer` gespeichert. Nach veröffentlichter Historie wird ein Mapping nicht still auf eine andere Immobilie umgebogen: explizite neue Mappinggeneration mit neuer Prüfung. Historische Originale behalten ihren ursprünglichen Ort.

### `provider_property_periods`

`id`, `portfolio_id`, `connection_id`, `mapping_id` optional bis zur Bestätigung, `external_object_id`, `external_period_number`, `transport_lieg_nr`, `period_from`, `period_to`, `source_snapshot`, `source_sha256`, `last_seen_run`, `availability`, `revision`.

Eindeutig `(connection_id, external_object_id, external_period_number)`. Weder Periode noch Datenzeile wird als eigene Immobilie angelegt. Beobachtete Datumformate und Nullwerte werden streng am realen Beispiel normalisiert; Originalwerte bleiben in der Herkunft enthalten. Eine fehlende Zeile in einem fehlgeschlagenen/abgebrochenen Scan wird nicht als gelöscht betrachtet.

### `provider_document_sources`

Stabile lokale Quelle: `id`, `portfolio_id`, `connection_id`, `mapping_id`, `external_document_ref`, `transport_lieg_nr`, `document_id` optional bis Veröffentlichung, `head_item_id`, `revision`. Eindeutige Quelle innerhalb der bestätigten Provider-/Objektgrenze. `reference` ist opaque: nicht parsen, nicht als Pfad oder Dateiname verwenden. Vor echter Datenanalyse nicht voraussetzen, dass eine Referenz providerweit global eindeutig ist.

Eine Remote-Referenz kann bei Folgeläufen unveränderte Bytes, neue Metadaten oder neue Bytes liefern. Diese Fälle bleiben unterscheidbar. Gleiche Hashwerte bei unterschiedlichen Remote-Referenzen rechtfertigen keine Zusammenführung fachlich unterschiedlicher Belege. Geänderte Bytes derselben bestätigten Quelle erzeugen eine neue Dokumentfassung; `/uploads/...` des ursprünglichen Originals bleibt unverändert.

### `provider_exchange_batches`, `provider_exchange_items`, `provider_exchange_chunks`

Batch: Portfolio/Verbindung, Modus `receive`, Antragsteller und ausführender Akteur, bestätigter Objektfilter, Adapter-/Mappinggeneration, Zustände, Cursor, Claimowner/Claimtoken/Lease/Fencingrevision, Gesamtzähler aus SQL, nächste Wiederholung, sichere Fehlercodes, Zeitstempel.

Item: Portfolio, Batch, Mapping, Providerquelle/Periode, eindeutiger logischer Arbeitsschlüssel, Metadaten-Snapshot/hash, Contenthash/Bytezahl, Herkunftstyp `document` oder später `technical_order`, Zustand `pending/fetched/needs_mapping/needs_review/published/unchanged/retryable/blocked`, lokale Dokument-/Originalversionreferenz, Zeitstempel. Ein fehlgeschlagenes Item stoppt nicht alle anderen zugeordneten Immobilien; Gesamtzustand kann `partial` sein.

Chunks: Item-ID, Portfolio, Position, Bytes, optional blockweise verschlüsselt bei als vertraulich definiertem Inboxspeicher. Sie halten tatsächlich abgerufene Originalbytes zwischen Vorschau und Freigabe dauerhaft fest; ein bloßer temporärer Dateipfad würde die Vorschau bei Serverneustart verlieren. Blockgrößen sind technische Arbeitsbudgets, kein Beleggrößen- oder Datensatzlimit. Nach Veröffentlichung darf ein bestätigter Wartungslauf den doppelten Staginginhalt entfernen, sobald die verknüpfte unveränderliche Dokumentfassung in derselben Prüfung bytegleich nachgewiesen ist; Originalarchive und Journal bleiben erhalten.

### `provider_exchange_commands`, `provider_exchange_events`

Kommandos speichern Akteur + Idempotenzschlüssel + canonical Requesthash + Ergebnisreceipt. Gleicher Schlüssel und gleiche Anfrage gibt dasselbe Ergebnis, abweichende Anfrage 409. Events sind fortlaufend und unveränderlich: claim, fetched, checked, published, stopped, retry scheduled, conflict. Keine Credentials, Authorization-Header oder vollständigen personenbezogenen Responsebodies im allgemeinen Log.

Diese Tabellen sind ein Designvorschlag, keine Forderung nach maximaler Tabellenzahl. Bereits beschlossene P1-Job-/Vorgangsjournale sollen statt paralleler Infrastruktur genutzt werden, soweit ihre tatsächlichen Semantiken dieselben Schutzregeln erfüllen.

## 6. Interne API und Berechtigungen

Alle Beispiele sind neue interne Anwendungspfade, keine behaupteten TEHA-Endpunkte.

| Pfad | Verhalten |
| --- | --- |
| `POST /providers/teha/connections` | Verbindung im zugänglichen Portfolio anlegen; Owner/Verwalter, erwartete Konfiguration, Idempotenzschlüssel. |
| `GET /providers/teha/connections` | Zugängliche lokale Zustände; keine Credentials, Portalaccountliste oder Netzwerkaktion. |
| `PATCH /providers/teha/connections/{id}` | Aktivierung/Worker-Akteur über erwartete Revision; Zugangsdaten separat ersetzen, niemals `***` als reales Passwort speichern. |
| `PUT /providers/teha/connections/{id}/credentials` | Explizite secret-only Eingabe; Antwort nur configured/revision; volle Geheimnishülle atomar ersetzen. |
| `POST /providers/teha/connections/{id}/check` | Begrenzter tatsächlicher Verbindungstest als eigener Job; sicherer Status, keine Rohantwort. |
| `POST /providers/teha/connections/{id}/inventory-runs` | Dauerhaften Leseinventarlauf starten; Idempotenz. Noch ungemappte Remoteobjekte nur für ausdrücklich befugte Verbindungsverwalter. |
| `GET /providers/teha/connections/{id}/property-periods` | Paginierte lokale Inventardaten mit klarer Trennung Immobilie/Periode; Portalnummern nur für Befugte. |
| `PUT /providers/teha/connections/{id}/mappings/{external_object_id}` | Interne Immobilie bewusst zuordnen, erwartete Inventar-/Mappingrevision. Scope und alle Eltern frisch prüfen. |
| `POST /providers/teha/connections/{id}/receive-runs` | Bestätigte Mappings/Perioden selektieren; kein frei übergebener Endpunkt oder fremdes LiegNr. |
| `GET /providers/teha/runs/{run_id}` | Lokale Zähler, nächste Aktion, sicherer Fehler und Fortschritt. |
| `GET /providers/teha/runs/{run_id}/items?after=...&limit=...` | Keyset-Pagination; erlaubte positive Seitenbudgets ohne maximale Gesamtzahl. |
| `POST /providers/teha/items/{item_id}/publish` | Erwartete Item-/Mapping-/Dokumentrevision, Reviewhash und bestätigte Originalbytes; atomare Veröffentlichung plus Receipt. |
| `POST /providers/teha/runs/{run_id}/resume` | Wiederaufnahme mit derselben Worklist; Idempotenz, kein Neuanlegen derselben Belege. |
| `POST /providers/teha/runs/{run_id}/cancel` | Stopwunsch dauerhaft vormerken; bekannte Resultate fertig protokollieren, keine Originale löschen. |

Owner/Verwalter verwalten Verbindung und Zuordnungen. Buchhaltung kann im erlaubten Portfolio Dokumentempfang/Freigabe ausführen, sofern `documents` und die eigens definierte TEHA-Empfangsfähigkeit vorhanden sind. Techniker kann zugeordnete technische Aufträge empfangen, sofern `operations` vorhanden ist; diese Rolle erhält dadurch keine finanzielle Dokumentliste. Readonly liest lokal bereits veröffentlichte, ansonsten zugängliche Ergebnisse und Jobzusammenfassungen, startet weder Portalaufrufe noch Veröffentlichungen. Diese Rollenwahl muss im ADR für Produktentscheidung festgehalten und real per HTTP geprüft werden.

Es reicht nicht, `/providers` einfach auf die bestehende Defaultfähigkeit `administration` fallen zu lassen. Empfang, technische Projektion, Dokumentfreigabe und Verbindungspflege haben unterschiedliche Aktionen. Netzwerkjobs benötigen einen ausdrücklich konfigurierten, frisch gültigen Ausführungsakteur. Keine verlorene Benutzerbindung durch `scope_context(None)` reparieren.

## 7. Transport und Authentifizierung

HTTP-Client mit TLS-Prüfung, Verbindung-/Lesetimeout, kleinen Connectionpools und einer expliziten Allowlist beobachteter read-only Operationen. `list_documents` und `read_document` dürfen ihre tatsächlich beobachteten POSTs ausführen. Es gibt keinen generischen `request(method, url, payload)`-Button im Produkt.

Origin/Redirects begrenzen, Geheimnisse nur an die bestätigte Anbieter-Origin senden. Logfilter dürfen keine kompletten Requests/Responsebodies aufzeichnen. Die tatsächlich beobachtete Anmeldung sendet `POST /api/user` mit `Mandant=1`, Benutzername und unveränderter Passworteingabe im Feld `PasswordHash`; der Adapter darf keinen zusätzlichen Hash berechnen. Den Access-Token ausschließlich als Bearer für die bestätigte Origin verwenden. Sessionfortsetzung/Refresh wird erst nach eigenem Beleg implementiert, nicht aus der bloßen Existenz eines `refreshToken`-Feldes geraten.

Schema prüft `success`, fehlende Felder, Typen und fachliche Identitäten; HTML-Loginseite bei HTTP 200 ist kein erfolgreicher JSON-Empfang. Unbekannte Zusatzfelder bleiben als Herkunft erhalten, gefährliche Schemaänderungen werden als `provider_schema_changed` nachvollziehbar blockiert. Der alte lokal archivierte Bestand bleibt zugänglich.

Credentialverschlüsselung: bestehende unabhängige ENCRYPTION-Keyring-Konfiguration als Mastermaterial nutzen, einen separaten HKDF-Kontext `immomanager/provider.secret/v1` und eine randomisierte AEAD-Hülle mit Key-ID, zufälliger Nonce und AAD für Anbieter/Verbindung/Portfolio/Geheimnisart verwenden. Dies ist neu zu implementieren und zu prüfen; `IBANKeyring.encrypt()` nicht fachfremd wiederverwenden. Falscher Key, falsches Portfolio oder geänderte Hülle schlagen authentifiziert und ohne Secret im Fehler fehl. Keyrotation wird explizit wiederaufnehmbar, alte Keys bleiben bis bestätigtem Abschluss/Backup erhalten. JWT-Rotation darf Providergeheimnisse nicht unlesbar machen.

## 8. Incrementalität, große Bestände und Fortsetzung

Es ist bislang keine echte Anbieter-Delta-Schnittstelle belegt. Der ehrliche erste Algorithmus ist daher ein vollständiger Anbieterinventarabruf mit lokalem Vergleich und danach ein begrenzter Dokumentlauf pro Objekt. Keine erfundene `page`, `offset`, `since`-Query senden.

1. Der Inventarabruf wird in privater, budgetierter Verarbeitung eingelesen und jede vollständige Inventarzeile validiert. Für sehr große JSON-Antworten Streaming-Parser oder private Spoolverarbeitung vorsehen. Ein technisch anpassbares Antwortbudget ersetzt keine willkürliche Gesamtdatensatzgrenze.
2. Inventoryrun startet mit eigenem Runmarker. `last_seen_run` wird auf vollständig geprüfte Zeilen gesetzt. Erst nach bewiesen vollständigem Scan werden vorher bekannte, nicht mehr vorhandene Zeilen als `not_seen` markiert. Kein fachliches Löschen.
3. Arbeitsliste mit stabiler Sortierung `(mapping_id, external_period_number, work_id)` und lokal dauerhaftem Cursor einfrieren. Durch einen neuen Remoteeintrag darf ein Keysetcursor kein altes noch offenes Item überspringen: jede Runde hat eine explizite Worklist.
4. Pro bestätigtem Mapping Dokumentliste erneut abfragen. Ohne dokumentiertes Remote-Änderungssignal kann bytegleiche Vollständigkeit nur durch erneutes Lesen der relevanten Inhalte oder eine klar angezeigte Metadatenoptimierung mit periodischer Vollprüfung nachgewiesen werden. Dateiname/Datum allein ist kein Contenthash.
5. Kandidateninhalt stückweise Base64-dekodieren, SHA-256/Bytezahl berechnen, Magic/MIME prüfen und in Itemchunks halten. Base64 erhöht Transportgröße; konfigurierte Budgets unterscheiden Response-, dekodierte Datei-, RAM- und temporäre Größen. Eine Überschreitung liefert anpassbare, präzise Abhilfe und einen fortsetzbaren Itemzustand.
6. Dedup bindet Providerquelle + beobachtete Generation + tatsächlichen Contenthash; gleiche bereits publizierte Fassung wird `unchanged`. Revision/Metadatenänderung wird gesondert protokolliert. Nicht nur die letzten 100 oder 200 Belege betrachten.
7. Freigabe hält eine kurze lokale Transaktion: frisch gültiger Akteur → Portfolio/Immobilie → Mapping/Quelle → Item/Dokument. Erwartete Revisionen/Reviewhash, vollständige Stagingblöcke und Contenthash prüfen. Document, Originalversion und Providerreceipt gemeinsam schreiben; kein Netzwerk unter diesen Locks.
8. Nach erfolgreicher Veröffentlichung Cursor und Zähler committen. Absturz vor Commit: derselbe idempotente Publish ist wiederholbar. Absturz nach Commit vor HTTP-Antwort: dasselbe Receipt zurückgeben. Nebenläufige Worker konkurrieren um einen persistierten Claim mit Token/Fencingrevision.

Claims besitzen endliche Lease und erneuern sie kontrolliert. Nach Ablauf darf ein anderer Worker lesen, der alte Worker kann mit veraltetem Token nichts mehr veröffentlichen. Portalabfragen werden außerhalb der DB-Transaktion durchgeführt; jede anschließende Veröffentlichung prüft frische Akteur-/Mapping-/Credentialgeneration. Credentialwechsel während einer Abfrage führt nicht zur stillen Veröffentlichung in der falschen Verbindung.

429/503/temporäre Netzwerkfehler: exponentieller, gedeckelter Backoff mit Jitter und beobachtetem `Retry-After`, keine enge Schleife. 401: einmalige kontrollierte Authentifizierung nach tatsächlich bestätigter Semantik, danach `credentials_required`. Dauerhafte Schemakonflikte: `blocked` mit genauer betroffener Operation, bereits abgeschlossene Items bleiben erhalten. Cancel: kein neuer Request nach Stopmarker, tatsächliches bereits empfangenes Ergebnis sicher abschließen oder als Kandidat behalten.

Arbeit pro Runde/CPU-/Speicher-/Zeitbudget ist konfigurierbar. Datenmengen, Laufzahl, Zahl der Immobilien oder Zahl der Dokumente haben keine Produktobergrenze. Große Historien werden vollständig mit Keyset-Cursorn zugänglich; SQL aggregiert Gesamtzähler. Der erste große-Bestandsbeleg muss mehr als 100/200/10.000 Items enthalten und Fortsetzung statt unkontrollierter Materialisierung zeigen.

## 9. Dokumente und technische Termine fachlich behandeln

Dokumenteigenschaften zuerst am aktuell ausgewählten Transportobjekt validieren. `properties.Liegenschafts_ID`, `Liegenschafts_Nummer`, `Abrechnung_laufende_Nummer` sind keine schon bewiesenen identischen Alternativen zu Inventarfeldern. Konflikt wird sichtbar, nicht durch den Dateinamen aufgelöst.

Originale behalten Quelle, Abrufzeit, Providerreferenz, Periode, Rohmetadaten, tatsächlichen Hash, Adapterversion und alle bestätigten lokalen Beziehungen. Rechnungs-/Gesamtabrechnungsbelege werden noch nicht automatisch zu einer internen Buchung oder Rechnung: ursprüngliches Dokument empfangen und gesonderten überprüfbaren Fachimport anbieten. So entstehen keine doppelten Forderungen oder Kosten.

`Mieter_ID` oder `Nutzereinheit_ID` dürfen nur mit explizitem periodengültigem Nutzer-/Einheitsmapping einen lokalen Mieterbezug ergeben. Ein Objekt-Gesamtbeleg wird dadurch nicht in jeden Mieterexport aufgenommen. Bereits vorhandene Original-/Datenschutzregeln bleiben maßgeblich. Die neuen Providerjournale müssen persönliche Felder als solche im Tenantgraph berücksichtigen, wenn sie tatsächlich einem Mieter zugeordnet werden.

Technische Aufträge zunächst als Providerbeobachtung empfangen. Die belegte Detailstrecke verwendet `terminId`; `auftragNummer` bleibt eine andere fachliche Referenz. Die Referenzen in getrennten Feldern speichern. `nutzerInAuftrag` enthält persönliche Kontakte; nur zugeordnete Immobilie/Einheit und ausdrücklich befugte Nutzer dürfen diese Daten sehen. Noch unbekannte Status-ID-Bedeutungen werden als Providerstatus angezeigt und nicht als eigene erledigte Aufgabe interpretiert. Stabile Quellenidentität und Tombstone bewahren: manuell erledigte oder gelöschte lokale Aufgabe nicht bei jedem Sync neu anlegen. Provider-Solltermine und lokaler Plantermin sind getrennte Felder; Fremddaten überschreiben keine lokalen Notizen, Handwerker oder eigenständigen Projekte.

## 10. Recovery und Wartung

Neue Familie all-or-nothing prüfen: alle erforderlichen Tabellen/Spalten vorhanden oder vollständiges älteres Image ohne diese Familie. Ein halb fehlendes Journal darf `create_all()` nicht still reparieren. Pure Prüfer vor jedem Runtime-/Recovery-DML und vor Veröffentlichung des Restores ausführen.

Beweise prüfen: Mapping/Portfolio/Immobilie stimmig; Quelle/Periode/Item konsistent; Commandreceipt eindeutig; Eventfolge unverändert; Originalhash/Bytezahl/Chunkpositionen korrekt; ein published Item zeigt auf seine tatsächliche unveränderliche Dokumentfassung. Noch ungeprüfte Inboxbytes erhalten denselben Scope und werden in Fullbackup vollständig erfasst.

Provider-Secretentschlüsselung gegen die gesicherte explizite Konfiguration beweisen, ohne Netzwerk oder Login. Fehlende Keys ergeben reparierbares Recoveryproblem vor Veröffentlichung des neuen Verzeichnisses. Session-Signerschlüssel weiterhin unabhängig rotieren. Restore darf niemals automatisch TEHA kontaktieren oder Kosten/Nutzerdaten senden; Worker startet nach Wiederinbetriebnahme erst gemäß explizitem lokalen Lauf-/Leasezustand.

Der private PostgreSQLpfad benötigt dieselben semantischen Prüfer wie SQLite. Reine Zeilenzählungen sind nicht ausreichend. Encrypted DB/Appdata-Backup bereits vorhanden; neue Kapazitäts-/Secret-/Workerfelder in Compose, Serverkonfiguration und Backup-Allowlist konsistent behandeln.

Teiltransfer darf weder Journale schweigend auslassen noch published Ursprungsdokumente/Mappingidentitäten ersetzen. Entweder Modul explizit mitsamt Originalen exportieren oder die Teiloperation verständlich verweigern und vorhandenen vollständigen Recoveryweg nennen. Objekte/Quellen mit veröffentlichtem Beleg werden archiviert; keine Retentionshistorie durch gewöhnliches Löschen verlieren.

## 11. Abnahme in sinnvoller Reihenfolge

1. Transportvertragsfixtures aus tatsächlich beobachteter Form, bereinigt mit künstlichen Werten: 4 Perioden/2 Objekte, numerische Identitäten, `LiegNr` als String, zwei Referenzen, Base64-PDF. Negative Varianten: HTML200, `success=false`, fehlender Inhalt, falsche Objekt-/Periode, ungültiges Base64, Magic/Dateitypabweichung. Keine synthetische Fixture als reale Portalabnahme ausgeben.
2. Secretprüfungen: Maskierung in Responses/Logs, falscher Key/AAD, Keyrotation, Recovery ohne/mit korrektem Keyring und unabhängige JWT-Rotation.
3. Reale HTTP-Rollen-/Portfolioabnahme, inklusive Buchhaltung ohne Kalenderrechte, Techniker ohne finanzielle Rohdaten, Readonly, fremdes Portfolio, entzogenes Grant oder deaktivierter Worker zwischen Fetch und Publish.
4. SQLite + PostgreSQL: Migration vom wirklichen Althead, unversionierter Legacy-create_all-Pfad, Teilfamilie abweisen, CAS, zwei Worker, abgelaufene Lease und alte Fencingrevision, Idempotenz bei verlorener Antwort, Absturz nach Empfang/Chunks und vor/nach Veröffentlichung.
5. Größerer Bestand: über 10.000 dokumentierte lokale Arbeitseinträge, positive kleine Batch-/Seitenbudgets, alle erreichbar, keine 100-/200-Grenze, SQL-Gesamtzähler, Restart ab Mitte. Anbieterpaging nur testen, wenn tatsächlich unterstützt.
6. Originale: zweiter gleicher Lauf erzeugt keine zusätzlichen Originalfassungen; geändertes Remote-PDF erzeugt bewusst eine neue Fassung mit altem Original noch herunterladbar. Metadatenrevision/Referenzkollision und neue Periode bleiben getrennt.
7. Recovery: SQLitevollimage und private PostgreSQL-/Appdataprobe mit tatsächlicher Bytegleichheit aller veröffentlichten und noch wartenden Kandidaten, erhaltenem Journal, widerrufenen internen Sessions; kein Portalzugriff während Restore.
8. End-to-End-UI: Verbindung → Inventar → zwei Immobilien mit jeweils Perioden → tatsächliches Original empfangen/vorschauen/freigeben → erneut unverändert → Fehler/Fortsetzung. Mobil, Tastatur, keine UI-Secretanzeige, klare Projekt-/Dokumentzuordnung.
9. Tatsächliche Root-Liveabnahme der fertigen Anwendung gegen das eigene Portal: Inventar und mindestens ein konkretes Original lokal durch den Adapter empfangen, gegenüber dem beobachteten Anbieter-PDF bytegleich abgleichen. Aktuelle Root-Browserbeobachtung ist ausreichender Protokollbeleg für die Planung, noch kein Abnahmetest des neuen Programmcodes.

## 12. Noch gezielt zu beobachten

- Token-Expiry und Refresh sowie Fehlermeldungen bei abgelaufener Sitzung; normaler Login und Bearer-Bindung sind inzwischen live belegt. Keine vertraulichen Werte dokumentieren.
- Tatsächliche Typen/Nullwerte/Datumsformate und Identitätsgleichheit zwischen Inventar- und Dokumentproperties; Umnummerierung oder Wechsel der Periode.
- Dokumentreferenz-/VERSION-Semantik, mögliche Attachments, vollständige Listen über mehrere Perioden, Umgang mit leeren Dokumentbeständen und Fehlerantworten.
- Technische Aufträge: Bedeutungen der Status-IDs, weitere Termin-/Dokumentstrecken und Zuordnung der Nutzer-IDs; Auftragliste und Nutzerdetail über `terminId` sind inzwischen live belegt.
- Sichtbare Anbietergrenzen/Rate-Limit-/Sessionfehler erst aus beobachteten Antworten ableiten.
- Kosten-/Nutzerübermittlung und Restarbeitsauftrag sind spätere eigene Schreibverträge mit Vorschau/Bestätigung/unklarem-Ausgang-Verfahren. Nicht aus Read-Only-Livebelegen implementieren oder automatisch absenden.

## 13. Erste überschaubare Umsetzungseinheit

Ein erstes vollständiges Paket liefert geschützte Verbindung, beobachteten Transport, zugeordnete Immobilien/Perioden, dauerhaften Dokumentempfang mit Originalvorschau und Wiederaufnahme. Danach: lokale Freigabe ins vorhandene Dokumentarchiv, Recovery und tatsächlicher Portalabgleich. Technikprojektion erhält erst anschließend ihren separat bestätigten Vertrag. Damit ist die erste Anbindung praktisch verwendbar, ohne einen geratenen Provider-Schreibvorgang oder das gesamte künftige TEHA-Fachmodell vorwegzunehmen.
