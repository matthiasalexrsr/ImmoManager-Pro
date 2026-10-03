# Paket C: Domainübergabe Widerspruchsjournal

Stand 03.10.2026, eigener Checkout `work/measurement-parent-guards`.
Die Parent-/Privacy-Vorgänger bis `ef9ee25` sind bereits an Root übergeben.
Der lokale Basiscommit `7a037ed` übernimmt ausschließlich die von Root
freigegebene f2-Metadatenreparatur und deren eigenständige Regression aus
`b64341a`; er gehört nicht zum erneut zu übernehmenden Journalprodukt.
Keine Änderung an Root, Main, Preview oder dem früheren Historycheckout.

## Umgesetztes Verhalten und Datenbasis

Neue Widersprüche benötigen eine konkrete finalisierte Einzelabrechnung mit
Revision, Originalhash, Grund und tatsächlichem Eingang. Die Vorschau bindet
den vollständigen bestätigten Befehl, beanstandete Positionen und tatsächlich
archivierte Dokumentversionen. Bestätigen schreibt eine Akte, einen
unveränderlichen Befehl mit exakter Quittung, ein Originalereignis und
Originalbelegverknüpfungen atomar. Gleicher Actor/Idempotenzschlüssel und Inhalt
liefert dieselbe Quittung; anderer Inhalt oder alte Revision liefert 409.

Nachfolgende Notizen, Prüfstand, Rücknahme, Abschluss, Wiederaufnahme und
Berichtigungen sind weitere Ereignisse. Eine Berichtigung nennt das erhaltene
frühere Ereignis. Eine ausdrücklich verknüpfte Korrekturabrechnung benötigt
ihren echten finalisierten Hash und eine Quellenkette zur beanstandeten
Einzelabrechnung derselben Mietpartei. Ursprünglicher Grund, Eingang,
Abrechnungsfassung und Anlagen bleiben unverändert.

Bestehende `UtilityStatement`-Datensätze speichern Vertrag/Einheit, aber keine
eingefrorene frühere Mieteridentität. Deshalb ist `party_binding` ausdrücklich
`verified_at_case_opening`: Die aktuelle Vertragspartei wird beim Eröffnen
geprüft und dann eingefroren. Es wird keine historische Person erfunden.
Detail- und Datenschutztext benennen diese Einschränkung. Änderungen der
ursprünglichen Vertrags-/Einheiten-/Portfoliozuordnung werden danach geschützt.

Der andere Typ `property_review` benötigt eine tatsächliche bestätigte
Eigentümerabrechnungsgrundlage und besitzt keinen willkürlichen Mieterbezug.
`GET /periods/{period_id}/status` liefert dafür `property_review_original` und
`property_review_snapshot_hash`, sofern diese Grundlage existiert.

Die neue Akte verändert weder den Sammelperiodenstatus noch Forderungen,
Erstattungen oder Zustellungen. Zustellung einer anderen Einzelabrechnung
bleibt möglich. Der alte unvollständige Queryparameter-Endpunkt `/dispute`
antwortet 400 mit einem handlungsfähigen Hinweis zum neuen Ablauf. Vorhandene
`disputed`-Altperioden bleiben unverändert und werden bei fehlender vollständiger
Akte als `legacy_disputed_without_complete_case` angezeigt.

## HTTP-Vertrag für die Oberfläche

Basis `/api/v1/billing/disputes`, authentifiziert, `Cache-Control: private, no-store`.
Alle vertraulichen Texte werden als JSON übertragen.

| Aktion | Route/Ergebnis |
| --- | --- |
| Eröffnung prüfen | `POST /preview`, 200 mit `request`, `binding`, `evidence`, `preview_hash` |
| Eröffnung bestätigen | `POST ''`, 201 mit `{case_id, revision, event_id}` |
| Arbeitsübersicht | `GET ''`, Filter `property_id`, `period_id`, `tenant_id`, `state`, Keyset `after_id`, `page_size` |
| Akte/Originalfassung | `GET /{case_id}` einschließlich `original_snapshot`, `latest_event` und Hinweis zur Personenbindung |
| Chronik | `GET /{case_id}/journal?after=0&page_size=50`, `next_after` nach bestätigter Revision |
| Originalereignis | `GET /{case_id}/events/{event_id}` |
| Folgeereignis prüfen | `POST /{case_id}/preview` |
| Folgeereignis bestätigen | `POST /{case_id}/events`, 200 mit exakter Quittung |
| Periodenübersicht | `GET /periods/{period_id}/status`, Anzahl/offene Akten, Altstatus und Objektprüfgrundlage |

`OpenDispute`: `expected_case_revision=0`, `case_kind=tenant_statement`,
`period_id`, `statement_id`, `expected_statement_revision`,
`expected_snapshot_hash`, ISO-Datum `received_on`, `reason`,
`idempotency_key`, optionale `line_item_refs` (Originalindizes ab 0) und
`evidence_version_ids` (bestehende unveränderliche Versionen).
Objektprüfung: `case_kind=property_review`, keine Statement-/Positionsbezüge,
Hash aus der ausdrücklich geprüften Objektprüfgrundlage.

`AppendDisputeEvent`: `expected_revision`, `kind`, `reason`, ISO-Datum
`observed_on`, `idempotency_key`, optionale `evidence_version_ids`.
`kind` ist `note`, `in_review`, `withdrawn`, `closed`, `reopened`, `correction`
oder `correction_link`. Nur `correction` verlangt `corrects_event_id`; nur
`correction_link` verlangt `correction_statement_id`.

Zur Bestätigung das vollständig unveränderte DTO plus zurückgegebenem
`preview_hash` verwenden. Bei Änderungen Vorschau neu laden. Bei verlorener
Antwort exakt denselben Befehl wiederholen; keine neue Kennung erfinden.
Listen und Chronik sind auf höchstens 200 Einträge je Seite begrenzt, besitzen
aber keine Höchstzahl über die Lebensdauer. Fremde Akten sind 404; gefilterte
Listen verraten sie nicht. Vollständige Datenschutzoperationen bei teilweise
verdeckter Historie sind 403.

Originalbelege enthalten `document_id`, `version_id`, `filename`, `media_type`,
`size_bytes`, `sha256`. Den vorhandenen authentifizierten Download
`/api/v1/documents/{document_id}/versions/{version_id}/download` nutzen; er
prüft tatsächliche Originalbytes. Vorschau und Publikation prüfen die Bytes
gestreamt. Abrechnungsoriginalhashes werden SQL-seitig nach Statement-ID
gestreamt in exakt der bestehenden Settlement-JSON-Darstellung geprüft.

## Zentrale Einbindung durch Root

Migration ausschließlich `j2a2b3c4d5e6 → h2a2b3c4d5e6`. Das bereits bestehende
historische i2 bleibt unverändert. Journalmigration erzeugt keine globale
Index-Metadatenmutation und erfindet aus Altstatus keine Journalfakten.
Downgrade einer nicht leeren Familie wird vor DDL abgewiesen.

1. `backend.db.billing_dispute_models.DISPUTE_MODELS` bzw. `DISPUTE_TABLES`
   früh in der zentralen Modellregistrierung einbinden, einschließlich frischem
   Bootstrap und Migrations-/Recoveryskripten.
2. `validate_dispute_schema(connection)` und
   `validate_dispute_guards(connection)` aus `billing_dispute_schema` in die
   zentralen Nativechecks aufnehmen. Beide unterstützen SQLAlchemy-Verbindungen
   und echte `sqlite3.Connection`; sie führen keinerlei Reparatur oder DDL aus.
   Vollständig fehlende Familie liefert bei Schema False; teilweise Familie
   oder geänderter/fehlender Originaltrigger ist ein Integritätsfehler.
3. Vollbackup-Familien aus `billing_dispute_recovery.RESTORE_ORDER` in dieser
   FK-Reihenfolge aufnehmen: `billing_dispute_cases`,
   `billing_dispute_commands`, `billing_dispute_events`,
   `billing_dispute_evidence`. Export über `iter_dispute_family(store, name)`;
   natürliche Datumsfelder: Cases/Commands `created_at`, Events `created_at`
   und `observed_on`. Selbstbezug Events ist nach Case/Revision geordnet.
4. Vor Restore-Publikation `VALIDATE_SNAPSHOT(family, parents=parents)` aus
   `billing_dispute_recovery` aufrufen. `RESTORE_PARENTS` benennt Portfolios,
   Properties, Units, Contracts, Tenants, BillingPeriods, UtilityStatements und
   DocumentVersions, jeweils Maps nach ID. Der reine Validator prüft vollständige
   Familien, Quittungen/Befehlstexte, Fassung/Positionen, Zustands- und Hashketten,
   Quellen-/Personenbindung sowie tatsächliche Settlement-Originalhashes. Er
   normalisiert Statements mit dem bestehenden Pydantic-JSON-Vertrag.
5. `guard_partial_transfer(store)` vor Geschäftsdatenteilimport/Reset verwenden.
   Vorhandene Journaloriginale verlangen vollständiges Recovery; Memory
   `clear_all` ist bereits verbunden. SQL/common Transfer bleibt Rootbesitz.
6. Genauigkeit der vollständigen Originalanlagenfamilie einschließlich
   DocumentVersionChunks beibehalten. SQL-FKs sind RESTRICT; Journalereignisse,
   Befehle und Beleglinks sind nativ unveränderlich. Cases erlauben nur eine
   folgende Revision und abgeleiteten Prüfstand, niemals geänderte Bindung.

Parenthelpers und Memory-/SQL-Publikation sind hier verbunden. Datenschutz
exportiert ausschließlich exakt eingefrorene Akten dieser Person, minimale
Befehlsquittungen und verifizierte Originalbytes. Private Requests anderer
Personen und reine Objektprüfungen fehlen im Mieterexport. Anonymisierung
erhält Originalgrund/Actor/Datum/Anlagen ausdrücklich und bindet die Vorschau
an Änderungen der Chronik. Account-/Operational-/Immobiliensperren schützen
auch die Abwesenheit einer ersten Akte.

## Gezielte tatsächliche Abnahme

Alle Daten synthetisch; PG verwendet ausschließlich zufällige eigene Schemas
des freigegebenen lokalen Clusters, keine public-Schemas oder Dienständerungen.

- `dispute-journal-native-postgres-fixed.log`: 8 PASS, keine Skips, 90,55 s.
  Enthält tatsächlichen Erstschreiber-INSERT mit Eventbarrieren, unabhängige
  PostgreSQL-Sitzung mit real gesperrtem Advisory Lock und konkurrierendem 409,
  exakte Wiederholung; außerdem tatsächlichen Rollenverlust nach INSERT.
- `dispute-journal-recovery-final2.log`: 10 PASS, 2 Memory-Skips, 88,10 s.
  Memory/SQLite/PG-Origin-/Befehl-/Zustandsvalidator; tatsächliche SQL-DML-
  Originalgrenzen; leere und historische h2↔j2-Up-/Downgrade-Rundreise.
- `dispute-journal-states-backup.log`: 3 PASS, 2 Backend-Skips, 22,73 s.
  Darin tatsächliches SQLite-Connection-Backup und frisch geöffneter Store
  samt ursprünglichem Grund, Raw-SQLite-Guards und geprüftem Anlagenhash.
- `dispute-journal-publication-originals.log`: 6 PASS, 4 Backend-Skips, 57,26 s.
  Tatsächliche ursprüngliche Anlagenbytes im Privacyexport; native Memory-
  Rollen-/Tokenänderung mit Rollback und native SQL-Publikationsprüfung.
- `dispute-journal-stream-composition.log`: sechs bestandene Fälle einschließlich
  PostgreSQL-Original-/Korrekturhash und f2-Migration→frischer Metadatenaufbau;
  ein gültiger Memory-Restore wegen UTC-Darstellung abgewiesen. Die Ursache ist
  im aktuellen reinen Validator behoben und im final2-Gate erneut geprüft.
- `dispute-journal-api-originals-final.log`: 10 PASS, keine Skips, 51,87 s.
  Memory/SQLite/PG-Akten mit echtem Originalversionsdownload und SHA256,
  Objektprüfgrundlage über die echte API, reiner vollständiger Restorevalidator
  sowie die vier berührten bisherigen Abrechnungs-/Altstatusfälle.
- Ruff der neuen und berührten Domainquellen sowie `git diff --check` grün;
  Mypy der acht neuen produktiven Dateien grün.

Der erste PostgreSQL-Versuch zeigte den tatsächlichen JSON-Gleichheitsfehler
im Case-Trigger. Installation und reine Guardprüfung verwenden nun den
expliziten PostgreSQL-Textvergleich der JSON-Originalfassung; der strikte
8-Fälle-Nachlauf ist grün. Frühere fehlgeschlagene Fixture-/Validatorversuche
sind keine bestandenen Belege; die benannten finalen Nachläufe ersetzen sie.

Offen außerhalb dieses Domaincheckouts: zentrale Root-Recovery-/Startup-
Komposition und die neue Oberfläche mit echtem Browserlauf. Es gibt keinen
behaupteten vollständigen A–L-Gesamtgate oder Widerspruchs-UI-Abschluss.
