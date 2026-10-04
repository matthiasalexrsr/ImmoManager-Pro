# Paket I – Offline-Verifikation, Legacy-Konvertierung, Ressourcenpolitik und CAS

Prerequisite/resource+CAS commit: `0d26a173d2fef86c2c100191d6bfa44341baa43f`
Original base: `7b6073f96106f0fc2efdb51430f53e5de75a69bb`
Branch/Checkout: `assist/integration-connections` / `work/integration-connections`

Dieser Folgebaustein ändert ausschließlich den DDL-freien
Integrations-Config-/Connection-Bereich. Keine Root/Main/Preview-, UI-,
Recovery-, Startup-, Bank-, Workflow- oder Providertransportdatei wurde
verändert. Es wurde keine Migration angelegt. Korrigierter Graphhinweis:
historisches `i2` existiert bereits; die Domain-Folge
`j2a2b3c4d5e6 -> h2` ist anderweitig reserviert.

## 1. Ressourcenpolitik ohne willkürliche Obergrenzen

`JsonFileIntegrationConfigStore` und
`EncryptedJsonIntegrationConfigStore` behalten ihre bisherigen Defaults:

- Statebudget: **1 MiB**
- Locktimeout: **5 Sekunden**
- JSON-Tiefe: **64**

Entfernt wurden ausschließlich die künstlichen Maxima von 16 MiB und 60
Sekunden. Explizite Budgets müssen jetzt nur positive Integerbytes bzw. positive
endliche Zeiten sein; boolesche Werte gelten nicht als Zahlen.

Die bisher feste Tiefe 64 ist nun `max_json_depth`: eine benannte
Ressourcenpolitik pro Store. Ein höherer expliziter Wert ist zulässig; unbekannte
Providerfelder werden nicht wegen fehlender statischer Kenntnis entfernt. Ein
Parser-/Ressourcenfehler bleibt fail-closed und wird niemals als erfolgreich
gekürzter Zustand ausgegeben.

Dateilesen benutzt nach überprüftem Handle die tatsächliche Dateigröße statt
`maximum + 1`; sehr hohe konfigurierte Budgets erzeugen dadurch keinen
unnötigen riesigen Read-Request.

## 2. Rein lesender Archivverifier

Neu:
`backend/services/integrations/integration_state_offline.py`

`verify_encrypted_integration_state(path, explicit_configuration, ...)`:

- benutzt ausschließlich den expliziten Dateipfad;
- benutzt ausschließlich `keyring_from_configuration(explicit_configuration)`;
- liest keine Runtime-Settings/.env, keinen Default-Keyring und keine Liveauth;
- öffnet den State read-only, ohne Sidecar-/State-/mtime-Mutation;
- prüft Regular-File-/Handleidentität, Envelopeform, AES-GCM/AAD, JSONstruktur,
  vollständige Statevalidität und Ressourcenbudgets;
- falscher Key, manipuliertes Ciphertext, Klartext oder kaputtes Envelope
  failen typisiert;
- Ausgabe enthält nur nichtgeheime Metadaten: Format, Key-ID, Bytegrößen,
  Ciphertext-Dateirevision und Zählwerte. Keine Configwerte, Secrets oder
  Ciphertextbytes.

Der Test ersetzt `history_crypto.current_keyring` und Liveauth absichtlich
durch Funktionen, die bei Benutzung hart fehlschlagen. Der Verifier bleibt
davon unabhängig.

### Präziser Root-Recovery-Hook

Root kann vor Zielpublikation den unveränderten Archivpfad plus die bereits
aus dem Archiv gelesene Konfigurationsmap an
`verify_encrypted_integration_state` geben. Der Verifier besitzt keine
Restore-DML und ändert kein Ziel. Die eigentliche Full-Recovery-Komposition
bleibt Root-owned.

## 3. Expliziter Offline-/Maintenance-Konvertierungsweg

**Aktualisierung 03.10., zentrale Komposition:** Der unten dokumentierte
isolierte frühere `migrate-plaintext`-Aufruf wird vom Programm jetzt mit
`fenced_maintenance_required` abgelehnt. Umstellung erfolgt ausschließlich über
`python -m backend.integration_state_upgrade convert --data-dir <installation>
--output <neues-vollarchiv> --offline`, einschließlich Lebenszyklus-Sperre,
tatsächlicher Vollsicherung/Wiederherstellungsprobe und geprüftem Rückweg.
Die früheren Helper-Prüfzahlen belegen diese neue Komposition nicht.
`verify` bleibt die unveränderte explizite, nur lesende Prüfung.

Neu:
`scripts/integration_state_maintenance.py`

Beispiele:

- `python scripts/integration_state_maintenance.py verify --state-file <path> --configuration <archive-config.json>`
- `python scripts/integration_state_maintenance.py migrate-plaintext --state-file <path> --configuration <archive-config.json>`

Eigenschaften:

- State- und Konfigurationsdatei sind Pflichtargumente;
- keine Settings/.env-/Liveauth-Fallbacks;
- Konfigurationsdatei hat ein eigenes positives, frei erhöhbares Workbudget;
- Klartext wird vollständig validiert, bevor verschlüsselte Bytes erzeugt
  werden;
- Veröffentlichung nutzt die bestehende Lock/temp/fsync/`os.replace`-Grenze;
- vor Replace bleibt der alte Klartext byteidentisch, danach ist nur der neue
  Envelope der Statepfad;
- es wird **kein Klartext-Backup-/Rollbackfile** erzeugt;
- gültiger bereits verschlüsselter Zustand ist idempotent;
- stdout/stderr enthalten nur Status/Fehlercode und nicht Config, Secret oder
  Ciphertext.

## 4. Opaque CAS-/Revisionvertrag

Alle drei ConfigStores besitzen nun `load_with_revision()` und
`update_if_revision(expected_revision, mutate)`.

Für Dateistores ist die Revision SHA-256 über die **exakten gespeicherten
Dateibytes**. Beim verschlüsselten Store ist dies deshalb ein Hash über den
zufälligen Ciphertext-Envelope, nicht über Klartext/Secrets. CAS-Vergleich und
Mutation passieren unter derselben Store-Sperre.

Stale Revision:
- `state_revision_conflict`
- keinerlei Mutation
- keine Secret-/Unknown-Field-Verluste.

Der Manager besitzt additiv:
- `connection_state(integration_id)`
- `update_connection_state(... expected_revision ...)`

Der Merge verwendet weiterhin `preserve_config_masks`; `***` ersetzt kein
bestehendes Secret. Unbekannte verschachtelte Felder bleiben erhalten.

Additive HTTP-Hooks:
- `GET /integrations/{id}/connection-state`
- `PATCH /integrations/{id}/connection-state`

PATCH verlangt eine 64-stellige Revision sowie mindestens `enabled` oder
`config`. Stale CAS wird als HTTP **412** mit
`state_revision_conflict` projiziert. Bestehende Legacy-PUT/PATCH-Endpunkte
bleiben unverändert; Root kann die UI später bewusst auf CAS umstellen.

## 5. Vorbereitungsfactory, keine globale Aktivierung

Neu:
`build_encrypted_integration_store(path, explicit_configuration, ...)`

Die Factory konstruiert ausschließlich einen Store mit explizitem Stable-Keyring
und expliziten Ressourcenbudgets. Sie:
- initialisiert keine Datei,
- migriert keinen Klartext,
- liest keine Settings,
- ruft keinen Provider auf.

Der globale `integration_manager` bleibt weiterhin auf seinem bisherigen
Storepfad. Root soll den verschlüsselten Store erst nach erfolgreich integrierter
Upgrade-/Recoveryverifikation global aktivieren.

## 6. Connection-Test bleibt ehrlich und nebenwirkungsfrei

Der bestehende DDL-freie Connection-Test wurde nicht in einen Business-Run
umgebaut. Die vorhandenen Gates bleiben:

- SMTP ohne explizites Probecontract:
  `status=not_supported`
- `network_checked=false`
- `business_action_performed=false`
- `test_message_sent=false`
- keine Demo-Mail und kein `provider.run(...)`.

Die parallele UI-Umstellung durch Root wird hier nicht berührt.

## 7. Ausgeführte Gates

Fokussierte lokale Suite:

`pytest backend/tests/test_integration_config_atomicity.py backend/tests/test_integration_encrypted_config_store.py backend/tests/test_integration_connection_contract.py backend/tests/test_integration_state_offline_cas.py backend/tests/test_integration_manager.py backend/tests/test_integrations_router.py -q -rs --tb=short`

Ergebnis: **38 passed, 5 skipped**, eine bestehende
Starlette-TestClient-Deprecation-Warnung. Die fünf Skips sind die bewusst nicht
gestarteten PostgreSQL-Parameter des bestehenden Managerfixtures; dieser Auftrag
verlangte ausdrücklich keine schweren PG-/Browsergates.

Neue Gegenproben umfassen:
- >16-MiB-Konfigurationsbudget und >60-s-Locktimeout konstruktiv akzeptiert;
- bool/0/negativ/NaN Budgets abgewiesen;
- Defaulttiefe 64 fail-closed, explizit höhere Tiefe erhält unbekannte Felder;
- verifier read-only, unveränderte Bytes/mtime/Verzeichnis, kein Ambientkey/Auth;
- falscher Archivkey fail-closed;
- Factory erzeugt keine Datei;
- verschlüsselter CAS erhält Secret+Unknown Fields und stale CAS mutiert nichts;
- CLI Klartext→Encrypted ohne Secret-Ausgabe, idempotenter zweiter Lauf;
- CLI-Fehler lässt alte Klartextbytes exakt unverändert;
- HTTP-CAS liefert Revision und stale 412;
- Connection-Test bleibt ohne Mail/Businessaktion.

Statisch:
- Ruff auf allen geänderten Produkt-/Test-/CLI-Dateien: **grün**.
- Mypy auf ConfigStore, EncryptedStore, OfflineVerifier, Manager und Router:
  **Success: no issues found in 5 source files**.
- `py_compile`: **grün**.
- `git diff --check`: **grün**.

Keine echten Providerzugänge, Privatdaten, Liveaktionen oder Modelldownloads
wurden verwendet.
