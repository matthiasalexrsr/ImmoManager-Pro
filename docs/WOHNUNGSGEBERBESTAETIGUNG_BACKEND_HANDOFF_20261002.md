# Wohnungsgeberbestätigung – Backend-Handoff

Basis: `679c8de9a97074f513bf611f7c636d40f2002fea`  
Branch/Worktree: `assist/housing-confirmation` / `work/housing-confirmation`

Verbindlicher Plan: `docs/WOHNUNGSGEBERBESTAETIGUNG_PLAN_20261002.md`.

## Umfang

Das Paket implementiert den Backendkern für eine lokale
Wohnungsgeberbestätigung. Es fügt **keine neue Fachtabelle und keine Migration**
hinzu. Veröffentlichte Bestätigungen sind bestehende `Document`-Datensätze mit
einem bestehenden unveränderlichen `DocumentVersion`-Original und Chunks.

Es gibt keine elektronische Unterschrift, keine Melderegister-/Behördenanbindung
und keine Zustell-/Übermittlungsbehauptung. Das PDF enthält ausdrücklich nur
einen Platz für die tatsächliche Unterschrift. Die Implementierung behauptet
keine rechtliche Zertifizierung.

## HTTP-/DTO-Vertrag

Neuer Router:
`backend/routers/housing_confirmations.py`

Prefix:
`/contracts/{contract_id}/housing-confirmations`

### GET /source

Liefert ausschließlich den frisch autorisierten exakten Vertrag samt
Portfolio/Immobilie/Einheit/Mieter und optional der exakt gebundenen
veröffentlichten Vertragsassistent-Quelle.

`source_etags` bindet:
- Portfolio
- Vertrag
- Immobilie
- Einheit
- Mieter
- optional den vollständigen verwendeten Wizard-Quellstand per Digest.

Vorschläge:
- Wohnungsgebername/-anschrift nur aus einem exakt gebundenen veröffentlichten
  Vertragsassistentenstand;
- Eigentümername, soweit im Portfolio vorhanden;
- Wohnungsanschrift/-bezeichnung aus Objekt/Einheit;
- Hauptmietername nur als **Vorschlag** für die Personenliste;
- Vertragsbeginn nur als Referenz.

`actual_move_in_date` bleibt absichtlich `null`. Vertragsbeginn oder
Übergabetermin werden nicht als tatsächlicher Einzug erfunden.

### POST /preview und POST /preview-pdf

Body `PreviewRequest`:
- `data: CertificateData`
- `source_etags: SourceEtags`
- optional `correction_of: {document_id, version_id}`.

`CertificateData`:
- `housing_provider_name`
- `housing_provider_address`
- `owner_same_as_provider`
- ggf. `owner_name`
- `move_in_date`
- `issue_date`
- `apartment_address`
- optional `apartment_label`
- `issuer_name`
- `issuer_role: housing_provider | authorized_person`
- nicht leere, geordnete `residents: string[]`.

Gleichnamige Personen werden nicht dedupliziert. Namen werden nicht in
Vor-/Nachnamen zerlegt. Es gibt keine feste Personen- oder Jahresgrenze.

Preview ist zustandsfrei. Der Reviewhash bindet normalisierte Eingaben,
Quellsnapshot/-revisionen, Korrekturbezug, PDF-Formatversion und PDF-SHA256.

### POST /

Body `SaveRequest` erweitert Preview um:
- `idempotency_key`
- `review_hash`
- `confirmed_actual_move_in=true`
- `confirmed_authority=true`
- `confirmed_residents=true`.

Alle drei Bestätigungen sind Pflicht. Vor der Mutation werden aktuelle
Berechtigungen und Quellen erneut geprüft. Geänderte Source-Revisionen geben
412; abweichende Reviewfassung/Idempotenz ergibt 409.

Die Dokument-ID ist deterministisch aus Actor + Command-Key abgeleitet.
Erfolgreicher Retry liest und prüft das vorhandene Original vollständig und
legt weder zweites Dokument noch zweite Version an. Derselbe Key mit anderen
Eingaben wird abgewiesen. Ein harmloser späterer Anzeigename/-typ des
`Document` erzwingt beim identischen Retry keine neue Vorschau; die
unveränderliche Erstfassung bleibt maßgeblich.

### GET /?after=&limit=

Keyset-Seite auf den archivierten Erstfassungen. SQL filtert
Vertrag + `metadata_snapshot.document_type=housing_confirmation` vor dem
Seitenlimit. Kein 100/10.000-Prefetch. Memory hält nur `limit+1` beste Treffer,
obwohl die autorisierte Collection vollständig durchsucht wird.

### GET /{document_id}/download

Liefert die verifizierten archivierten Originalbytes. Die bestehende
DocumentVersion-Downloadroute bleibt ebenfalls gültig.

## Persistenz und Originalbeweis

`backend/services/document_versions.py` erhält nur eine additive optionale
`metadata_extra`-Möglichkeit für den internen
`publish_generated_original`-Pfad. Ohne Argument bleibt das bisherige
Manifest byte-/datenkompatibel.

Unter `metadata_snapshot.housing_confirmation` werden gespeichert:
- Schema-Version
- vollständiger Review
- Reviewhash
- Requesthash
- Actor-ID
- ursprünglicher Idempotenz-Key
- alle drei expliziten Bestätigungen.

Der Featurevalidator rekonstruiert und prüft:
- typisierte Eingaben und Source-ETags,
- Reviewhash,
- PDF-SHA gegen Version-SHA,
- Actor/Requesthash,
- deterministische Document-ID aus Actor + Key,
- generische interne Version-Command-ID,
- Property/Unit/Contract/Tenant/Portfolio-Beziehung,
- exakten reservierten Dateipfad,
- Ausstellungsdatum gegen Dokumentdatum,
- Korrekturreferenz.

Der Offline-DocumentVersion-Validator ruft diese Prüfung für
`housing_confirmation` ebenfalls auf. Nur für diesen Typ wird dazu dessen
vollständige Feature-Metadatenstruktur gelesen; andere Dokumentversionen behalten
ihren bisherigen bounded Identity-Projektionspfad.

## Korrekturen statt Überschreiben

Ein freigegebenes Housing-Original wird nicht über die generische
DocumentVersion-Upload-/Restore-Funktion ersetzt. Diese Route lehnt
`housing_confirmation` sowie bereits mit Feature-Metadaten gebundene
Housing-Historien ab.

Eine Korrektur ist ein neues Dokument/Original mit explizitem
`correction_of {document_id, version_id}`. Das referenzierte Original wird
vollständig authorisiert, Manifest + Bytes geprüft und muss zum selben Vertrag
gehören. Die alte Fassung bleibt unverändert.

Liste, Retry und Download orientieren sich am archivierten Snapshot, nicht an
später editierbaren Anzeige-Metadaten des normalen Document-Datensatzes.

## Reservierter Dateipfad

`/uploads/housing-confirmations/<uuid>.pdf` ist virtuell reserviert.
`backend/routers/files.py` löst diesen Schlüssel nach normaler Scope-Prüfung
über das verifizierte archivierte Original auf. Eine zufällig/absichtlich
physisch gespeicherte Datei unter demselben Key gewinnt nicht.

## Atomarität, Scope, Rollen

SQL:
- eigener Session-/Transaktionsbereich;
- technischer Writer wird vor DML begonnen;
- `lock_subject_write_fence` schützt aktuellen Tenant-/Contract-/Location-
  Zusammenhang gegen Privacy-/Parallelwriter;
- erzeugtes `Document`, Manifest und alle Chunks werden ohne Repository-
  Zwischencommit in derselben Transaktion geschrieben.

Memory:
- bestehender gemeinsamer Privacy/Domain-Lock;
- Undo nur für konkret eingefügte Dokument-/Version-/Chunk-Keys, keine Kopie
  einer langjährigen Gesamtsammlung.

Freigabe verlangt gleichzeitig bestehende `contracts`- und `documents`-
Schreibrechte. Damit sind nach aktuellem Rollenmodell Eigentümer und Verwaltung
schreibberechtigt; Buchhaltung/Technik/readonly nicht. Lesen bleibt zusätzlich
an den aktuellen Portfolio-Scope gebunden.

Es werden keinerlei Booking-, Payment-, Receivable-, RentCharge-, Deposit- oder
andere Finanzbuchungen erzeugt.

## Datenschutz-/Retention-Grenze

Der vorhandene Tenant-DocumentVersion-Graph exportiert den unveränderlichen
Metadata-Snapshot dieses Originals für den exakt gebundenen Tenant/Vertrag. Die
bestehende Profile-Anonymisierung verändert ihn nicht.

Damit bleiben auch frei eingegebene weitere Haushaltsnamen im Original und
seinem Snapshot erhalten. Sie werden **nicht** als erfundene Tenant-IDs
interpretiert und nicht über Namen gesucht. Diese Profilaktion ist ausdrücklich
keine Beleglöschung.

## PDF

Eigener ReportLab-Renderer, keine Markenlogos und keine übernommenen
Vertragsformulierungen. A4, Seitenzahlen, ruhige Schwarz/Grau-Gestaltung,
wiederholte Tabellenüberschrift für Personen, Unterschriftsplatz und
mehrseitiges Splitting. Eingabetext wird escaped.

Für die eingebettete Schrift wird die mit ReportLab verfügbare Vera-TTF genutzt;
die synthetischen Gates enthalten Umlaute und erweitertes Latein
(`ÄÖÜ é č Ł –`) sowie 45 Personen.

Eine zusätzliche PDF-Text-Extractor-Bibliothek ist in der vorhandenen
Testumgebung nicht installiert. Deshalb wird hier **nicht behauptet**, die
mehrseitige PDF-Textauslese oder visuelle Browserdarstellung bereits geprüft zu
haben. Root muss diese beiden Akzeptanzpunkte wie im Plan vorgesehen bei der
Komposition prüfen.

## Tests / Gates

Featuretests:
- Memory + echtes SQLite: Sourcevorschläge, tatsächliches Einzugsdatum,
  Multi-Person/Unicode, Preview/PDF, atomare Publikation, identischer Replay,
  anderer Payload mit gleichem Key, 412 bei Sourceänderung, Korrekturoriginal,
  Cursorliste, beschädigte Metadaten, HTTP 401/403/404/422, reservierter
  Dateipfad, Wizard-Quelle, Rollback nach Chunkpersistierung, Fremdportfolio/
  Rechteentzug, Retention durch Profilanonymisierung, spätere
  Document-Metadatenänderung und Verbot generischer Housing-Versionen.
- Offline SQLite: gültiges Original akzeptiert; manipulierte Offline-Kopie
  wird vor Recovery-Nutzung abgewiesen.
- echtes PostgreSQL 16.15 auf `127.0.0.1:58112`, pro Test eigenes zufälliges
  `housing_confirmation_<uuid>`-Schema: Publish/Replay, SQL-Keyset-Liste,
  Offline-DocumentVersion-Validator, stale source sowie paralleler Same-Key-
  Writer mit Ereignisbarriere und anschließendem sicheren Replay. `public`
  wird nicht beschrieben.
- bestehende Korrespondenz-/Generated-Original-Smokes und generische
  DocumentVersion-Memory/SQLite-Smokes werden separat ausgeführt.

Keine echten Mieter-, Behörden- oder Providerdaten wurden verwendet.

## Root-Integration

Root muss nach Prüfung:
1. den neuen Router in der Produkt-App registrieren;
2. Frontendvertrag/UI an diese DTOs binden;
3. die zusammengesetzten Recovery-/Privacy-/Startup-Gates erneut laufen lassen;
4. echte Browser-/PDF-QA einschließlich Textauslese, Seitenumbruch,
   Fußzeilenabstand und 320/360/1440-UI durchführen.

Keine neue Migration/Startup-Tabelle ist für dieses Feature erforderlich.


## Final ausgeführte Prüfungen im Featurebranch

Finale kombinierte Feature-Suite mit gesetztem
`TEST_SERVER_DATABASE_URL=postgresql://immo_ci@127.0.0.1:58112/immo_ci`:

`pytest backend/tests/test_housing_confirmation.py backend/tests/test_housing_confirmation_postgres.py -q -rs --tb=short`

Ergebnis: **34 passed, 2 skipped**, eine bestehende
Starlette-TestClient-Deprecation-Warnung. Die beiden Skips sind ausschließlich
die Memory-Parameter der zwei SQL/offline-spezifischen Validatorproben; die
SQLite-Varianten liefen. Die zwei PostgreSQL-Tests liefen real in eigenen
zufälligen Schemas einschließlich Parallelwriter, Keyset-Liste und
Offline-DocumentVersion-Validator.

Kompatibilitäts-Smokes:
- bestehende Korrespondenz-Generated-Original-Freigabe, Memory + SQLite;
- bestehende Korrespondenz-Metadatenänderung, Memory + SQLite;
- generische DocumentVersion-Original/Version/Restore-Probe, Memory;
- dieselbe generische Probe separat auf echtem SQLite.

Die erste kombinierte Smoke-Auswahl ergab **5 passed**; die separate
SQLite-DocumentVersion-Probe **1 passed**.

Statisch:
- Ruff auf allen geänderten/neuen Python-Dateien: **grün**;
- konfigurierte Mypy-Prüfung der fünf neuen Runtime-/Routermodule:
  **Success: no issues found in 5 source files**;
- `py_compile`: **grün**;
- `git diff --check`: **grün**;
- neue Runtime-/Routerdateien sind UTF-8 ohne BOM;
- nach den PostgreSQL-Gates: **keine**
  `housing_confirmation_%`-Testschema-Reste.

Nicht als grün behauptet werden die vollständige Backend-/Frontend-/Browser-
Suite und die visuelle/PDF-Textauslese-Akzeptanz; diese bleiben bewusst Root-
Kompositionsgates.
