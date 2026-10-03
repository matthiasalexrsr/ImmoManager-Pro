# Paket I / TEHA – Mapping-/Importreceipt-Persistenz

Branch/Checkout: `assist/teha-receive-domain` /
`work/teha-receive-domain`.

Voraussetzung im selben Branch:
`8c85fb4fd5160de4759f0871e13c10144092d6d7`
(DDL-freier Receive-/History-/Preview-/Projektionskern).

Root hat für dieses Paket exklusiv reserviert:

- Revision: `l2a2b3c4d5e6`
- Parent: `k2a2b3c4d5e6`

Dieser Commit enthält **nur** Modelle, read-only Schemaerkennung,
Append-only-DB-Guards, die reservierte Migration und synthetische Persistenztests.
Keine zentrale Modellregistrierung, Startup-, Recovery-/Retained-, Settings-,
ConnectionStore-, CI-, Router- oder Shared-Job-Core-Datei wird verändert.

## Relationaler Vertrag

### `teha_external_mappings`

Eine Zeile ist eine bewusst bestätigte Mappinggeneration. Korrekturen
überschreiben keine Zeile, sondern erzeugen Generation N+1.

Persistiert werden nur:

- `portfolio_id`
- nichtgeheimer `connection_key`
- `kind`
- `external_identity_hash`
- `external_identity_json`
- genau **eine** lokale Ziel-ID
- `generation`, `revision`
- Actor/Zeit
- `source_history_run_id`
- vollständiger bereinigter `source_sha256`

Zulässige Kinds/Ziele:

- property -> property
- period -> billing_period
- unit -> unit
- user -> tenant
- technical_order -> task

`external_identity_json` ist auf die bereits belegten opaque
Identitätskomponenten begrenzt:

- property: `object_id`
- period: `object_id + period_number`
- unit: `lieg_nr + unit_id`
- user: `termin_id + user_id`
- technical_order: `termin_id`

Der Helper `validate_identity_binding()` rekonstruiert den kanonischen
Identitätshash und verweigert zusätzliche Schlüssel. Namen, Adressen,
Bewohnernamen, Kontaktfelder, Tokens, Passwörter oder andere Providerwerte
gehören nicht in diese Relation.

Die DB-Zeile ist append-only. Ein neuer Mappingstand benötigt eine neue
Generation; UPDATE/DELETE wird auf SQLite und PostgreSQL durch Trigger
abgewiesen.

### `teha_import_receipts`

Ein Receipt beweist eine **lokal bestätigte** Übernahme. Es ist kein
Provider-Schreibbeleg.

Gemeinsame Bindungen:

- Portfolio + Connection
- optional vorhandener OperationalJob/WorkItem
- exakter `source_history_run_id`
- `external_identity_hash`
- `mapping_generation`
- Source-SHA
- Actor/Command-CAS
- Importzeit

Zwei derzeit unterstützte Übernahmeformen:

1. `source_kind=document`
   - Content-SHA erforderlich;
   - `document_id + document_version_id` erforderlich;
   - kein Task.
2. `source_kind=technical_order`
   - kein Content-SHA;
   - genau `task_id`;
   - keine Document-ID.

Der existierende DocumentVersion-Kern bleibt Eigentümer der Originalbytes.
Das Receipt speichert keine PDFbytes, kein Base64 und keine unbekannten
Providerfelder.

Dedup:

- `(imported_by, command_key)` für Befehlsreplay;
- Dokumentversion: Connection + externe Identität + Source-SHA + Content-SHA;
- Technikauftrag: Connection + externe Identität + Source-SHA.

Receipts sind vollständig immutable; UPDATE/DELETE wird DB-seitig abgewiesen.

## Schema-/Migrationsvertrag

`backend/db/teha_receive_schema.py`:

- fehlende ganze Familie -> `False` (für Legacy/Root-Preflight);
- teilweise Familie -> `TehaReceiveSchemaError`;
- vollständige Familie -> Prüfung von Columns, PK, Unique-Indizes und exakten
  RESTRICT-FKs;
- keine DDL-Reparatur im Validator.

`l2a2b3c4d5e6_teha_receive_mapping_import.py`:

- `revision = "l2a2b3c4d5e6"`
- `down_revision = "k2a2b3c4d5e6"`
- unterstützt SQLite/PostgreSQL;
- Upgrade verweigert vorhandene/partielle Familie;
- Downgrade verweigert jede vorhandene Mapping-/Receiptzeile;
- legt keine zweite Queue, History oder Originaltabelle an.

Der isolierte Checkout basiert absichtlich auf dem älteren TEHA-Planstand und
enthält die zentral integrierte K2-Datei nicht selbst. Deshalb wurde **kein
vollständiger Alembic-Chainlauf** in diesem Branch behauptet. Root muss nach
Cherry-pick auf seinem aktuellen K2-Head den normalen
`alembic upgrade l2a2b3c4d5e6`-/Downgrade-Gate ausführen. Die Upgrade-/
Downgrade-Funktionen selbst wurden hier direkt auf echten SQLite- und
PostgreSQL-Verbindungen geprüft.

## Minimaler Shared-Job-Hook – nur Vorschlag, nicht implementiert

Der vorhandene `operational_jobs.py` ist heute statisch auf interne Familien
verdrahtet: `Family/FAMILIES`, `_source_query`, `_source_memory`,
`_upper`, `_discover` und `run_claim` dispatchen auf feste Fachquellen.

Für TEHA ist die kleinste gemeinsame Änderung nach Root-Abgleich:

1. `operational_job_types.py`: genau eine neue Family
   `"teha_receive"`.
2. `operational_jobs.py`: vor den internen SOURCE_MODELS-Zweigen für diese
   Family an einen schmalen
   `services.providers.teha_job_adapter` delegieren:
   - `upper(unit, parameters)`
   - `discover(unit, job, lane, width, deadline)`
   - `apply(unit, job, lane, item, width, deadline)`
3. Der Adapter schreibt ausschließlich vorhandene
   OperationalJob/Lane/WorkItem-Zustände und ruft den DDL-freien
   `JournaledTehaReader` für **read-only** Provideroperationen auf.
4. Raw-Providerdaten bleiben im verschlüsselten Integration-History-Run;
   WorkItem.result enthält nur Run-ID, Hashes, opaque Identitytoken und lokale
   Resume-/Previewmetadaten.
5. Kein automatischer Retry einer zukünftigen externen Schreiboperation.

Dieser Checkout ändert den Shared-Core nicht, weil C/B/Meter und Root diesen
Bereich parallel besitzen.

## Tatsächliche Nachweise

### DDL-/SQLite

`pytest backend/tests/test_teha_receive_persistence.py -q -k "not postgres" -rs --tb=short`

Ergebnis: **12 passed, 1 deselected**.

Abgedeckt:

- reservierte Revision/Parent;
- vollständige/partielle Familie;
- opaque IdentityJSON + Hashbindung;
- Namen/Kontakt/Secret-Zusatzfelder fail-closed;
- Generation N+1 statt Reparent-UPDATE;
- Mapping-/Receipt-DB-Immutabilität;
- Targetshape-Constraints;
- Document-/Task-Receipt-Dedup;
- leerer Downgrade grün, befüllter Downgrade blockiert.

### Echter PostgreSQL-Gate

Vor Ausführung ausdrücklich angekündigt. Verwendet ausschließlich
`postgresql://immo_ci@127.0.0.1:58112/immo_ci` mit einem zufälligen
`teha_receive_<uuid>`-Schema; das Schema wird im Fixture-Finalizer wieder
gelöscht. Kein Browser-/Portal-/Live-TEHA-Gate.

`pytest backend/tests/test_teha_receive_persistence.py::test_postgres_reserved_schema_migration_and_immutability -q -rs --tb=short`

Ergebnis: **1 passed**.

Der Test baut die echten prerequisite-FKs im isolierten Schema, führt die
reservierte Migration aus, validiert die Familie, schreibt eine synthetische
Mappinggeneration und beweist den PostgreSQL-Immutability-Trigger.

### Zusammengesetzte TEHA-Suite

Mit demselben isolierten PG-Gate:

`pytest backend/tests/test_teha_receive_persistence.py backend/tests/test_teha_receive_domain.py backend/tests/test_teha_transport.py backend/tests/test_teha_exchange_observation.py -q -rs --tb=short`

Ergebnis: **176 passed**, eine bereits vorhandene
Starlette-TestClient-Deprecation-Warnung.

Statisch:

- Ruff: **grün**
- Mypy auf Models/Schema: **Success: no issues found in 2 source files**
- `py_compile`: **grün**
- `git diff --check`: **grün**

## Root-owned Integrationsgrenzen

Nach Cherry-pick übernimmt Root weiterhin:

- zentrale Modell-/Metadata-Registrierung;
- K2->L2 Alembic-Chain-Gate;
- Recovery/Retained/Reset/Privacy-Familien;
- Startup/Settings/CI;
- globale verschlüsselte ConnectionStore-Aktivierung;
- Routeraktivierung;
- den oben beschriebenen Shared-OperationalJob-Hook nach Abstimmung.

Keine Liveproviderwerte, privaten Daten, automatischen Mails oder TEHA-
Schreibaktionen wurden verwendet oder als geprüft behauptet.
