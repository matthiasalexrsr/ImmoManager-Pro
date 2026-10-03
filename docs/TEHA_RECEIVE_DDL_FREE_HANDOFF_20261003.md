# Paket I / TEHA – DDL-freier Empfangsbaustein

Branch/Checkout: `assist/teha-receive-domain` /
`work/teha-receive-domain`.

Planbasis: `f6319160b962a6e2512353545ac4ec315ab278e8`.
Diese erste Produktstufe ist absichtlich DDL-frei. Keine Root-/Startup-/
Recovery-/Settings-/CI-Datei und keine zentrale Job-/History-/Originalfamilie
wird verändert.

## Tatsächliche Bausteine

### `teha_receive_contract.py`

Reine Domainlogik ohne DML/Provider-I/O:

- stabile externe Identitäten nur aus beobachteten opaque TEHA-Schlüsseln:
  Property `object_id`, Periode `object_id + period_number`,
  Dokument `lieg_nr + reference`, Einheit `lieg_nr + unit_id`,
  Nutzer `termin_id + user_id`, Technikauftrag `termin_id`;
- Source-SHA-256 über den kompletten bereinigten `source_snapshot()`,
  einschließlich unbekannter später Providerfelder;
- explizite Mappinganforderungen und Mappinggeneration, keine
  Namens-/Adress-/Kontakt-Heuristik;
- Previewzustände `new | unchanged | changed | conflicting`;
- ResumeCursor an History-Run + Source-SHA + Offset gebunden;
- Batchfortsetzung per Iterator/Offset ohne 100/10.000/Gesamtbestandsgrenze.

### `teha_journal_reader.py`

Schmale Brücke vom bestehenden read-only `TehaTransport` zum bereits
verschlüsselten `SQLIntegrationHistoryStore`:

- jeder TEHA-Read ist ein eigener `integration_id="teha"`-Run;
- accepted + execution_started werden vor dem Provideraufruf persistiert;
- terminal wird der vollständige bereinigte `PrivateJsonExchange` samt
  Schema gespeichert;
- Login-Credentials erscheinen weder im Historyrequest noch im Exchange;
- Dokument-Base64 wird nicht als zweites großes Historyoriginal gespeichert:
  die Responsebeobachtung enthält stattdessen SHA-256, Größe und Medientyp;
- unbekannte JSONfelder bleiben vollständig im verschlüsselten Historyartefakt;
- Provider-/Netzfehler werden als ungewisser Ausgang erfasst, genau ein
  Providercall, `automatic_retry=False`;
- wenn der terminale Historybeleg nicht vollständig gespeichert werden kann,
  wird kein erfolgreicher Empfang behauptet.

Es entsteht keine zweite Queue, kein zweites Historysystem und keine
automatische externe Wiederholung.

### `teha_import_projection.py`

Pure Projektion auf vorhandene Fach-DTOs:

- `DocumentCreate` für ein explizit gemapptes Ziel;
- erwarteter Original-SHA/Größe und History-Run als minimale Provenienz;
- `TaskCreate` für Technikauftrag immer lokal offen;
- externer Providerstatus oder unbekannte Rawfelder werden nicht als lokaler
  Abschluss/Tasktext gespiegelt;
- keine DML, keine Finanzbuchung.

### `teha_field_manifest.py`

Wertfreier, versionierter Katalog der tatsächlich beobachteten Feldnamen.
Er ist ausdrücklich **keine Allowlist**: unbekannte Felder werden nur als
`unknown` klassifiziert, aber im Source-Snapshot/Historybeleg nicht verworfen.

### `backend/routers/teha.py`

Bis zur persistenten Mapping-/Receive-Job-Stufe nur:

`GET /integrations/teha/field-manifest`

Der Endpoint ist lokal, führt keinerlei Provider-I/O aus und bleibt an die
bestehende installationsweite Owner/All-Scope-Verwalter-Grenze plus
`CheckedPublicationRoute` gebunden. Root besitzt die zentrale
Routerregistrierung.

## Nachweise

Fokussierte neue Domain-Suite:

`pytest backend/tests/test_teha_receive_domain.py -q -rs --tb=short`

Ergebnis: **12 passed**, eine bestehende Starlette-TestClient-
Deprecation-Warnung.

Gesamte vorhandene synthetische TEHA-Suite:

`pytest backend/tests/test_teha_receive_domain.py backend/tests/test_teha_transport.py backend/tests/test_teha_exchange_observation.py -q -rs --tb=short`

Ergebnis: **163 passed**, dieselbe bestehende Warnung.

Statisch:

- Ruff auf allen neuen TEHA-Domain-/Router-/Testdateien: **grün**;
- konfigurierte Mypy-Prüfung auf den fünf neuen Produktmodulen:
  **Success: no issues found in 5 source files**;
- `git diff --check`: **grün**.

Die Tests verwenden ausschließlich synthetische DTOs,
`httpx.MockTransport`, temporäre SQLite-History und synthetische Schlüssel.
Keine echten Portalwerte, Providerwrites, E-Mails oder privaten Daten.

## Persistenz folgt separat

Root hat danach die Revision
`l2a2b3c4d5e6` mit
`down_revision = k2a2b3c4d5e6`
ausschließlich für TEHA-Mapping-/Importreceipt-Domain reserviert.

Der nächste separate Commit enthält deshalb nur Domainmodelle,
Schema-/Migrationscode und eigene Persistenztests. Raw/unbekannte private
Quellfelder bleiben weiterhin ausschließlich im verschlüsselten
Integrationsjournal. Relationale IdentityJSON enthält nur opaque
Identitätskomponenten, niemals Namen, Adressen, Kontaktdaten oder Secrets.

Root bleibt Eigentümer von Modellregistrierung, Startup, Recovery/Retained,
Settings, CI und globalem verschlüsseltem ConnectionStore.
