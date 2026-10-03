# Paket I – Integrationsverbindungen, Geheimnisse und Parameterbelege

Stand: 03.10.2026  
Basis: `18ba896eff397bbe0e46e8a13864f4c33304a11a`  
Branch/Worktree: `assist/integration-connections` / `work/integration-connections`

Dieser Plan wurde **vor Produktcode** erstellt. Gelesen wurden
`IMPLEMENTATION_ROADMAP_20261003.md`, `IMPLEMENTIERUNGSPLAN_20261002.md`,
`TEHA_ADAPTER_ADR_20261002.md`, `ADAPTER_HISTORY_PLAN_20261002.md` sowie die
realen Integrations-, SMTP-, Outbox-, Verschlüsselungs- und Recoveryquellen.
Es wurden keine Providerzugänge, privaten Credentials oder Live-Schreibaktionen
verwendet.

## 1. Produktionsstart – nur lesende Vorprüfung

Der aktuelle Root-Checkout wurde ausschließlich gelesen. Für
`settings.is_production` geht `backend/dependencies.py:60-68` bereits über
`validate_runtime_schema(SessionLocal.kw["bind"])` und ruft `create_tables()`
nur im Nicht-Produktionszweig auf. `validate_runtime_schema` ist rein lesend
und verlangt den exakten Alembic-Head sowie alle deklarierten Tabellen/Spalten.

`backend/app.py:105-118` enthält weiterhin den allgemeinen
`AUTO_MIGRATE`-Zweig, aber `_validate_startup_config()` läuft davor und
verweigert `AUTO_MIGRATE=true` in Produktion. Deshalb darf dieser Pfad in
Produktion nicht erreicht werden.

`dependencies.py:107-119` initialisiert das History-Journal anschließend.
Das ist nur dann DDL-frei, wenn der vorherige Produktions-Schemacheck die
vollständige Familie bereits bestätigt hat; bei fehlender History-Tabelle muss
`validate_runtime_schema` vorher abbrechen. Root besitzt diesen Startcode und
seinen laufenden Gate89025; dieses Paket ändert ihn nicht.

## 2. Belegter heutiger Credential-Pfad

- `IntegrationManager` benutzt bei gesetztem `INTEGRATION_STATE_FILE`
  `JsonFileIntegrationConfigStore`.
- Die Datei wird atomar und mit Dateisperre geschrieben, enthält aber
  `state["config"]` **im Klartext**. Antwortmaskierung ändert nur die
  Projektion; sie schützt die dauerhafte Datei nicht.
- Heute bekannte Secrets sind u. a. SMTP-Passwort, WhatsApp-Token,
  Deutsche-Post-API-Key. Weitere Discoveryfelder dürfen nicht verloren gehen,
  nur weil sie noch nicht im statischen Manifest stehen.
- `integrations.json` ist bereits Bestandteil des Full-Backupformats und wird
  als JSON-Objekt gesichert. Ein JSON-Verschlüsselungsenvelope bleibt daher mit
  dem bestehenden Backupcontainer strukturell kompatibel.
- Der Stable-Keyring aus `iban_encryption.py` ist unabhängig vom JWT-Signer.
  `integrations/history_crypto.py` verwendet denselben Keyring mit
  HKDF+AES-GCM und versioniertem Envelope. Es wird **keine zweite Vault- oder
  Keyringfamilie** eingeführt.

## 3. Entscheidung ohne neue Migration

Native `/root/domain_sol` besitzt die reservierte lineare Migration
`i2 -> h2`. Dieses Paket legt deshalb **keine Migration und keine neue
SQL-Tabelle** an.

Der erste Produktbaustein ersetzt die Klartextdatei durch einen verschlüsselten
JSON-Envelope am **gleichen konfigurierten Pfad**:

```json
{
  "format": "immomanager/integration-state-encrypted/v1",
  "ciphertext": "history:v1:<key-id>:..."
}
```

Die Nutzdaten sind der vollständige bestehende Integrationszustand
(`enabled`, `config`, unbekannte zulässige Discoveryfelder). Verschlüsselt
wird mit dem vorhandenen Stable-Keyring und den vorhandenen
HistoryCrypto-Primitiven, aber mit eigener AAD-Identität
`kind=integration_config_state, version=1`. Dateipfad, JWT und Maschinenname
gehören **nicht** in die AAD, damit ein verifiziertes Vollbackup auf einem neuen
Host wiederherstellbar bleibt.

Die äußere Datei enthält keine Configwerte oder Secret-Hashes. Ciphertext oder
Fehlertexte werden nicht geloggt.

### Legacy-Klartext

Ein vorhandener Klartextzustand wird im normalen Start **nicht still
überschrieben**. Der Store erkennt ihn als
`plaintext_state_requires_migration`. Ein expliziter, atomarer
`migrate_legacy_plaintext()`-Schritt liest unter derselben Dateisperre,
validiert den kompletten Altzustand, verschlüsselt und veröffentlicht erst dann
den Envelope. Beschädigte/unsichere Dateien werden nicht repariert.

Root entscheidet, an welcher expliziten Maintenance-/Upgradegrenze dieser
einmalige Schritt aufgerufen wird. Bis dahin soll die Aktivierung des neuen
Stores auf bestehenden Klartextinstallationen fail-closed sein.

## 4. Trennung von Settings, Konfiguration und Secrets

- Settings enthalten nur Pfad, technische Budgets und den bereits vorhandenen
  Stable-Keyring. Provider-Credentials werden **nicht** als neue Settingsfelder
  eingeführt.
- Providerkonfiguration bleibt fachlich ein einzelner Zustand, ist aber
  vollständig verschlüsselt at rest. Dadurch bleiben auch noch nicht
  klassifizierte echte Discoveryfelder geschützt.
- Anzeigeprojektion bleibt `public_config(...)`; `***` ist ausschließlich
  UI-Maske und niemals persistierter Ersatzwert.
- `preserve_config_masks` bleibt die Schreibgrenze: ein maskierter Secretwert
  übernimmt den tatsächlich gespeicherten alten Wert, auch in verschachtelten
  Strukturen. Ein neues Secret muss als echter neuer Wert kommen.
- Backup/Restore enthält nur den verschlüsselten Envelope. Entschlüsselung nach
  Restore benutzt den **explizit wiederhergestellten Stable-Keyring**; kein JWT-
  oder Prozessfallback.

## 5. Verbindungsprüfung und externe Nebenwirkungen

Es werden drei Begriffe getrennt:

1. **configuration_valid** – lokale Typ-/Pflichtfeldprüfung; kein Netzwerk.
2. **connection_probe** – explizit implementierte, nebenwirkungsfreie
   Transport-/Loginprüfung eines Adapters. Kein Versand, kein Publish, kein
   Objektimport. Nicht implementierte Adapter melden `unsupported`, nicht
   Erfolg.
3. **business_action** – tatsächliche externe Aktion mit eigener
   Vorgangsidentität und History-Journal.

Für SMTP ist ein generischer Konfigurationstest **keine Testmail**.
Ein späterer echter SMTP-Probe darf höchstens Verbindung/TLS/Auth prüfen und
keine DATA-Nachricht übermitteln. Eine tatsächliche Testmail wird ausschließlich
als ausdrücklich erstellte Outbox-Nachricht an den vom Benutzer ausgewählten
Empfänger versendet; kein fest codierter Beispieladressat und kein
`IntegrationManager.run("email", demoPayload)` als Verbindungstest.

Dieses Paket führt ohne ausdrücklichen Benutzerauftrag **keinen** Live-SMTP-,
Portal-, TEHA-, WhatsApp- oder Post-Request aus.

## 6. Parameterbeobachtung: vier getrennte Zustände

Parameter werden nicht mit einer einzigen booleschen "unterstützt"-Aussage
vermischt:

- **discovered** – statisch/deklarativ im lokalen Provider oder in belegten
  externen Quellen gefunden;
- **observed** – in einem konkreten lokalen Adapterlauf oder importierten
  Anbieterartefakt tatsächlich gesehen;
- **mapped** – bewusst einem fachlichen ImmoManager-Feld/Objekt zugeordnet;
- **accepted** – durch menschliche/definierte Abnahme für den jeweiligen
  Import-/Exportweg bestätigt.

Jeder Eintrag behält Parametername, erwarteten Typ, Secret-Klassifikation,
Quelle/Evidence-Art, Provider/Action, optionale Fachzuordnung und Versionsstand.
`accepted` wird niemals aus `discovered` oder `observed` automatisch
abgeleitet. Unbekannte Felder bleiben geschützt erhalten und werden nicht wegen
fehlender Zuordnung verworfen.

Der persistente SQL-Katalog dafür wartet auf die abgestimmte Migration nach
`i2 -> h2`. Vorher kann ein rein additiver typed Katalog/Projektionskern ohne
DDL entstehen.

## 7. Erster implementierbarer Slice vor Schemaabstimmung

Ohne Migration werden implementiert:

1. `EncryptedJsonIntegrationConfigStore` als Wrapper um die bestehende
   atomare/gelockte JSON-Datei;
2. versionierter AEAD-Envelope über vorhandenen Keyring/HistoryCrypto;
3. fail-closed Load bei falschem/fehlendem Key, manipuliertem Ciphertext,
   Klartextdatei oder ungültigem State;
4. explizite atomare Legacy-Konvertierungsfunktion, nicht automatisch beim
   normalen Start;
5. Manager-Bootstrapoption für den verschlüsselten Store **erst nach**
   festgelegter Upgradegrenze; bis dahin getrennt testbar;
6. Tests für Secret-Nichtvorkommen in Datei, verschachtelte Discoveryfelder,
   Maskierungsupdate, falschen Key/AAD, atomaren Fehler und Backup-bytegenauen
   Envelope-Roundtrip;
7. typed Parameter-Evidence-Dataclasses und rein lokale
   `connection_test`-Semantik ohne Provider-I/O als nachfolgender
   DDL-freier Commit.

## 8. Root-/Recovery-Hooks nach Handoff

Root besitzt Startup/Recovery und `measurement_history_database.py`. Dieses
Paket editiert diese Dateien nicht. Für Integration sind später zentral zu
prüfen:

- `integrations.json` darf im Fullbackup weiterhin nur als opaque JSON-Envelope
  kopiert werden;
- Offline-Recovery muss bei vorhandenem encrypted-v1 Envelope die explizite
  Archiv-Keyringkonfiguration verwenden und Authentizität vor Zielpublikation
  prüfen;
- altes Klartextarchiv bleibt als **Legacyformat** lesbar, wird aber nicht
  während der Recovery heimlich neu verschlüsselt;
- fehlender/falscher Key verhindert die Zielveröffentlichung;
- kein Restore löst Providerlogin, Connection-Probe oder Business-Action aus.

## 9. Geplante Gates

Zunächst nur leichte statische/unitäre Gates; Gate89025 und
`/root/domain_sol` werden nicht konkurrierend belastet.

Nach Schema-/Rootabstimmung:
- Memory-Konfigmanager + verschlüsselte Datei;
- SQLite-Domain + verschlüsselte Datei;
- echte PostgreSQL-Fachintegration ausschließlich in zufälligem UUID-Schema,
  falls der Slice SQL berührt;
- Fullbackup/Fullrestore mit explizitem Keyring;
- Klartext-Legacy, falscher Key, manipulierte AAD/Ciphertext;
- parallele Configupdates ohne Secretverlust;
- HTTP-Maskierung und `***`-Nichtüberschreibung;
- Verbindungstest garantiert null Mail-/Portal-/TEHA-Schreibaktionen;
- Ruff, konfigurierte Typprüfung, keine neuen privaten Werte in Logs.

## 10. Ehrliche Grenzen

Dieser erste Slice ist noch **kein TEHA-Adapter** und keine behauptete
Providerkompatibilität. Er entdeckt oder testet keine privaten Konten. Ohne
abgestimmte neue Migration existieren noch keine `provider_connections`,
Mappings oder persistierten Parameter-Abnahmetabellen. Eine echte Testmail
bleibt Outbox-Arbeit; eine Konfig-/Connection-Prüfung behauptet keine
Zustellung.
