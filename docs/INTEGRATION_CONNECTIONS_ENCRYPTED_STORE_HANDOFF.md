# Paket I – verschlüsselter Integrationszustand, DDL-freier erster Slice

Basis: `18ba896eff397bbe0e46e8a13864f4c33304a11a`  
Plancommit: `2468c6ca0eafd1c90267dbe79e2749a64756a134`

## Enthalten

Neu ist `backend/services/integrations/encrypted_config_store.py`.

`EncryptedJsonIntegrationConfigStore` verwendet **keinen neuen Keyring und
keine neue Vault**. Er verwendet den bestehenden Stable-Keyring über
`integrations.history_crypto.ring_for/encrypt/decrypt`. Der vollständige
bestehende Integrationszustand wird als authentifizierter Ciphertext in einem
kleinen JSON-Envelope gespeichert:

- äußeres Format: `immomanager/integration-state-encrypted/v1`
- AAD-Identität: `integration_config_state/v1`
- keine Bindung an Pfad, Host oder JWT, damit Fullrestore portierbar bleibt
- unbekannte/nachträglich entdeckte JSON-Felder bleiben vollständig im
  verschlüsselten Payload
- der bestehende atomare Dateilock/`os.replace`-Pfad wird wiederverwendet

Der äußere Envelope bleibt ein JSON-Objekt. Damit kann der bestehende
Fullbackup-Container `integrations.json` weiterhin opak kopieren; die
Entschlüsselung/Authentizitätsprüfung mit der expliziten Archiv-Keyring-
Konfiguration bleibt ein Root-Recovery-Hook.

## Fail-closed

Normaler `load()/initialize()` akzeptiert **keinen** Klartextlegacyzustand.
Ein vorhandenes Klartextfile ergibt
`plaintext_state_requires_migration`.

Die explizite Methode `migrate_legacy_plaintext()` konvertiert unter derselben
Dateisperre atomar. Sie wird von diesem Paket **nirgendwo beim normalen Startup
aufgerufen**.

Falscher/fehlender Key oder manipuliertes Ciphertext ergibt einen festen
ConfigStore-Fehler ohne Credential-/Ciphertexttext. Ein fehlgeschlagener Update
publiziert weder Teilzustand noch Klartext.

## Maskierung

Der Store selbst speichert den echten vollständigen Zustand verschlüsselt.
UI-Maskierung bleibt Sache von `IntegrationManager.public_config` /
`preserve_config_masks`. Der synthetische Gate beweist, dass ein eingehendes
`"***"` das vorhandene echte SMTP-Passwort nicht ersetzt, während ein
unbekanntes verschachteltes Discoveryfeld gleichzeitig erhalten bleibt.

## Noch absichtlich nicht aktiviert

Dieser Commit ändert die globale Managerinitialisierung noch **nicht** von
`JsonFileIntegrationConfigStore` auf
`EncryptedJsonIntegrationConfigStore`.

Grund: bestehende Installationen können eine Klartext-`integrations.json`
besitzen. Root muss zuerst die explizite Maintenance-/Upgradegrenze für die
einmalige atomare Konvertierung festlegen. Eine stille Konvertierung im normalen
Produktionsstart wäre nicht akzeptabel.

Es gibt keine neue Migration. Die reservierte lineare Migration
`i2 -> h2` des Native Domain Agents bleibt unberührt.

## Ausgeführte leichte Gates

`pytest backend/tests/test_integration_encrypted_config_store.py -q -rs --tb=short`
→ **5 passed**

Zusätzlich:
- Ruff: **passed**
- Mypy auf `encrypted_config_store.py`: **Success, no issues found**
- `py_compile`: **passed**
- `git diff --check`: **passed**

Die Tests verwenden ausschließlich synthetische Keys und Werte. Kein
Provider-/Netzwerkaufruf, keine Privatdaten und keine Root/Main/Previewänderung.

## Root-Produktionsstart – lesender Befund

Auf dem aktuellen Root-Arbeitsstand wurde nur gelesen:

- `dependencies.py` ruft bei `settings.is_production`
  `validate_runtime_schema` auf und `create_tables()` nur sonst.
- `app.py` prüft die Produktionskonfiguration **vor** seinem allgemeinen
  `AUTO_MIGRATE`-Zweig; `AUTO_MIGRATE=true` ist dort ein harter
  Produktionsfehler.
- Das anschließend aufgerufene `create_history_tables()` kann im
  Produktionspfad nur nach erfolgreichem vollständigem Runtime-Schemacheck
  erreicht werden; bei fehlender deklarierter Historyfamilie muss
  `validate_runtime_schema` vorher abbrechen.

Dieses Paket editiert keine dieser Root-Startupquellen und behauptet nicht den
laufenden Gate89025 für sich.
